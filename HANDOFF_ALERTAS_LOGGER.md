# Handoff — Camada A (alertas), F (logger) e composição `avaliarForgeDirecao`

**Para**: a sessão do Claude Code que trabalha no repositório do app
principal (o app onde os alunos operam / o app de alertas / onde vive
`accounts`, `strategies`, `ledger`, `forge-logger.js`, `alertas-core.js`).

**Contexto**: este documento foi escrito na sessão que trabalha no
repositório `headguardiao/head` — o **Forge Heatmap Multiexchange**, um
microsserviço de mercado, à parte do app principal. As Camadas B, C e E
do briefing original (`FORGE_BRIEFING_CLAUDE.md`) já estão implementadas
e testadas lá. As Camadas A, F, D e a composição final
(`avaliarForgeDirecao`) **não existem em nenhum repositório que eu
tenha acesso** — ou vivem no app principal (que eu não vejo), ou ainda
não foram escritas. Este handoff dá tudo que falta pra implementar A, F
e a composição sem precisar reconsultar o briefing original.

**Regra-mãe, vale pra qualquer repositório**: ADD-ONLY. Não altere
`LIQUIDITY_SCORE`, os pesos PDF §7, o `bias` de paredes (±15%), a
`confidence = exchanges_conectadas/3*100`, nem os campos já existentes
de `/signal`/`/sentiment`. Novos campos só se acrescentam.

---

## 1. O que já existe no Forge (`headguardiao/head`) — pronto pra consumir

Serviço Python (`forge/app.py`, porta 8080 por padrão — ver
`config/settings.py` / `HTTP_HOST`/`HTTP_PORT`). Dois endpoints
relevantes:

### `GET /signal/{symbol}`

Book (Camada B) + Glassnode (Camada E) + sentimento de derivativos
(Camada C), tudo num payload só. Exemplo real capturado do código (sem
`GLASSNODE_API_KEY` e sem acesso à rede da Binance neste ambiente de
teste — por isso a maioria dos componentes aparece `avail: false`; é
exatamente o comportamento esperado quando uma fonte está fora do ar,
nunca um erro 500):

```json
{
  "symbol": "BTCUSDT",
  "liquidity_score": 28.2,
  "bias": "BULLISH",
  "concentration_above_usd": 303.0,
  "concentration_below_usd": 1500.0,
  "orderbook_imbalance": 0.664,
  "oi_change_pct": 0.0,
  "funding_rate": 0.0,
  "liquidation_notional_usd": 100.0,
  "top_liquidity_walls": [ { "price": 99.9975, "bid_notional_usd": 1500.0, "ask_notional_usd": 0.0 } ],
  "confidence": 100.0,
  "connected_exchanges": ["binance", "okx", "bybit"],
  "signal_ready": true,
  "min_confidence_required": 60,
  "glassnode": {
    "has_key": false,
    "asof": 1787785780,
    "asset_used": "BTC",
    "asset_direct": false,
    "interval": "1h",
    "glassnode_score": 0.0,
    "glassnode_bias": "NEUTRAL",
    "glassnode_confidence": 0.0,
    "components": { "sopr": { "value": null, "score": null, "avail": false }, "...": "7 outros, mesmo formato" },
    "notes": []
  },
  "sentiment": {
    "symbol": "BTCUSDT",
    "asof": 1787785780,
    "sentiment_score": -100.0,
    "sentiment_bias": "RISK_OFF",
    "sentiment_confidence": 11.1,
    "components": {
      "funding_z": { "value": null, "score": null, "avail": false },
      "liq_side": { "value": 1.0, "score": -100.0, "avail": true },
      "...": "7 outros, mesmo formato { value, score, avail }"
    },
    "notes": [],
    "btc_anchor": { "score": -100.0, "bias": "RISK_OFF" }
  }
}
```

**Campos pra usar na composição (Camada B, já existiam antes de tudo isso)**:
- `bias`: `BULLISH` | `BEARISH` | `NEUTRAL`
- `confidence`: 0–100 (cobertura de exchanges, **não é probabilidade de acerto**)
- `liquidity_score`: **não use como qualidade de trade** — é agitação do book.

### `GET /sentiment/{symbol}`

Só o bloco de sentimento de derivativos isolado (mesmo formato do bloco
`sentiment` acima). Aceita qualquer símbolo, mesmo um que o Forge não
esteja rastreando o book (só perde `liq_side` nesse caso).

### Env vars relevantes já implementadas no Forge

| Var | Efeito |
|---|---|
| `GLASSNODE_API_KEY` | liga o bloco `glassnode` (Camada E). Sem ela, `has_key:false`, sem quebrar nada. |
| `SIGNAL_MIN_CONFIDENCE` | limiar de `signal_ready` no `/signal` (default 60) |
| `FORGE_SENTIMENT_PROFILE` | perfil de peso do `glassnode`: `30m`\|`2h`\|`daily` (default `30m`) |
| `GLASSNODE_GATE` | liga `evaluate_glassnode_gate(...)` a devolver `block`/`reduce` de verdade — ver seção 3 |
| `FORGE_SENTIMENT_GATE` | idem, pro `evaluate_sentiment_gate(...)` da Camada C |
| `FORGE_ONCHAIN_GATE` | idem, pro `evaluate_onchain_gate(...)` da Camada D |

**Atualização: agora existe tanto em Python quanto em Node**, payload
idêntico nos dois (mesmas chaves, mesmo formato):
- Python: `GET /signal/{symbol}` (porta 8080) / `GET /sentiment/{symbol}`
- Node: `GET /api/score/:symbol` (porta 3000) / `GET /api/sentiment/:symbol`

Não importa qual dos dois serviços o app principal consome — o
contrato é o mesmo.

### Funções prontas pra composição (gates → app principal)

Cada camada tem uma função pura, exportada mas **não chamada
automaticamente** por nenhum endpoint (nenhuma delas sabe o lado
LONG/SHORT sozinha):

```python
# forge/engine/glassnode_sentiment.py
evaluate_glassnode_gate(components: dict, glassnode_score: float, glassnode_confidence: float, side: str, enabled: bool | None = None) -> str

# forge/engine/sentiment_engine.py
evaluate_sentiment_gate(sentiment_score: float, sentiment_confidence: float, side: str, enabled: bool | None = None) -> str

# forge/engine/onchain_engine.py
evaluate_onchain_gate(onchain_bias: str, peg_stressed: bool, confidence: float, side: str, enabled: bool | None = None) -> str
```

Equivalentes em Node: `evaluateGlassnodeGate`, `evaluateSentimentGate`,
`evaluateOnchainGate` (mesmos arquivos `.js` correspondentes em
`node/src/engine/`).

Regras de `evaluate_sentiment_gate` (Camada C, testadas em
`tests/test_sentiment_engine.py`):
```
LONG  + RISK_OFF (score<=-15) + |score|>=25 → block
SHORT + RISK_ON  (score>=15)  + |score|>=25 → block
NEUTRAL + confidence>=50 → reduce
gate desligado (padrão) → sempre "allow"
```

Regras de `evaluate_glassnode_gate` (Camada E, assimétricas — o
backtest tolera short melhor que long):
```
LONG  block se glassnode_score <= -12
LONG  block se (sopr>1.05 E sth_mvrv>1.2) OU mvrv>=2.4 OU netflow_score<=-50
SHORT block se glassnode_score >= +28
SHORT block se sth_sopr<0.97 E netflow_score>=+50
NEUTRAL + confidence>=50 → reduce
```

Regras de `evaluate_onchain_gate` (Camada D):
```
peg_stressed=true + LONG → block
NEUTRAL + confidence>=50 → reduce
```

É o app principal (você) que chama cada uma dessas, já sabendo o lado
da operação — em Python (importando direto, mesmo processo ou via
wrapper HTTP) ou replicando a mesma lógica aritmética (~10-20 linhas
cada) se o app principal for outra linguagem que não tenha acesso
direto ao Node/Python do Forge.

### Camada D (on-chain público) — atualização: já implementada

A Camada D foi implementada tanto no Python (`forge/engine/onchain_client.py`
+ `forge/engine/onchain_engine.py`) quanto no Node (`onchainClient.js` +
`onchainEngine.js`). Objeto irmão `onchain` dentro de `/signal/{symbol}`
(Python) / `/api/score/:symbol` (Node) — mesmo formato `{ value, score,
avail }` por componente que `glassnode` e `sentiment`, com
`onchain_score`, `onchain_bias`, `onchain_confidence`, `peg_stressed` e
`chain_used`. A seção 2 abaixo ("O que falta") não precisa mais cobrir
essa camada — já é só consumir.

**A Camada E (Glassnode) também foi recalibrada** desde a versão
anterior deste handoff — perfis de peso, fórmulas com a convenção
"positivo = RISK_ON = gasto no prejuízo é contrarian" (não é a leitura
ingênua), `notes` automáticas, gate assimétrico long/short, e
`close_time`/`closeTime` opcional pra leitura sem lookahead. Ver a
seção "Sentimento on-chain (Glassnode)" do `README.md` do repo do
Forge pros detalhes completos antes de consumir esse bloco.

### Clients HTTP prontos

Já mandei nesta conversa `forge_client.js` / `forge_client.py` /
`forge_client.php` — funções `getForgeSignal(symbol)` +
`checkStudentTrade(signal, side)`. Servem de base pra consumir
`/signal` e `/sentiment` daqui. Adaptar/estender conforme a stack real
do app principal.

---

## 2. O que falta implementar NO REPOSITÓRIO DO APP PRINCIPAL

### Camada A — Gatilho de gráfico (app de alertas)

Vive em `alertas-core.js` (ou equivalente) — **fora do Forge**. Regra
do vídeo DOGEUSDT 30m, textual e completa:

**Rompimento 30m:**
- close cruza SMA21 pra cima (long) ou pra baixo (short)
- SMA8 do mesmo lado da 21 (long: SMA8 > SMA21; short: SMA8 < SMA21)
- corpo da vela de rompimento fecha do lado do rompimento (não só pavio)
- SuperTrend 1/2/10 alinhado (long acima da linha, short abaixo) — é
  alinhamento, não precisa ser o flip na mesma vela

**Pullback:**
- 1 a 8 velas contrárias
- profundidade 1–3% a partir do extremo do rompimento (pode ultrapassar
  o candle de break)
- aborta se novo cruzamento contrário da 21, ou se passar de 8 velas

**Volume (comparação verde vs vermelho, NÃO RVOL vs SMA20):**
```
vol_break = volume da vela de rompimento
max_pb    = maior volume entre as velas do pullback
vol_entry = volume da vela a favor que encerra o pullback

RECUSA se max_pb > vol_break     // pullback maior que a venda/compra do rompimento
ENTRA  se vol_entry > max_pb     // volume a favor maior que o do pullback
as duas juntas = regra E (E lógico) do backtest
```

**Bagunçado (veto seco, não opera):**
- 3+ cruzamentos da SMA21 nas últimas 8 velas
- 3+ velas com pavio > 1.5× o corpo no bloco rompimento+pullback

**Flags:**
```
VIDEO_VOLUME_RULE=on   (default on)
MESSY_SKIP=on          (default on)
```

**Importante**: um gatilho só. Não somar Donchian + SuperTrend + SMA21
no mesmo alerta — ST e SMA8 são confirmação do rompimento da SMA21, não
gatilhos concorrentes.

Saída esperada dessa camada (usada na composição, seção 3):
```js
video_rule: { ok: boolean, vol_break, max_pb, vol_entry, messy: boolean }
```

Backtest de referência (pra calibrar expectativa, não pra "consertar" a
regra): regra falada sozinha, 95 pares/3 meses, n=6307, WR ~41%, PF
~0.80 (só short: WR ~44%/PF~0.94; só long: WR~38%/PF~0.67). A regra
sozinha não é o alpha — o alpha inclui os vetos do Forge (Camadas
B/C/E) em cima disso.

### Camada F — Logger

`forge-logger.js`, tabela `forge_score_log`. Chave de upsert
**existente, não mude**: `ativo,tipo,direcao,timeframe,sinal_fechamento_em`.

Adicionar colunas **nullable**, sem mudar a chave:
```
sentiment_score, sentiment_bias, sentiment_confidence, sentiment_components, sentiment_snapshot
onchain_score, onchain_bias, onchain_snapshot        -- Camada D já existe, ver seção 1
glassnode_score, glassnode_bias, glassnode_snapshot
video_rule_ok, messy, vol_break, max_pb, vol_entry
pnl_pct                                              -- quando o trade fechar, se já souber
```

Gravar snapshot **no fechamento do sinal, inclusive quando a decisão
for `block`**. Sem log do bloqueio não dá pra medir se o veto está
funcionando.

Também: um cron de 30 em 30 min gravando `/signal` + `/sentiment` de
**todos os símbolos rastreados**, mesmo sem alerta disparado — senão só
existe log nos candidatos que passaram pelo gatilho, e não dá pra medir
o veto contra o universo todo.

### Camada D — On-chain público (mempool.space + DefiLlama)

**Já implementada aqui no Forge** — ver a atualização na seção 1. O
objeto `onchain` só precisa ser consumido pelo app principal do mesmo
jeito que `glassnode` e `sentiment`.

---

## 3. Composição final — contrato de `avaliarForgeDirecao`

Isso é o que junta tudo. Vive no app principal (consome o Forge via
HTTP + o resultado da Camada A local). Campos velhos do seu
`avaliarForgeDirecao` continuam intactos; campos novos:

```js
{
  status, motivo, signal,                 // já existem (book) — não mudar
  sentiment, sentiment_gate,               // allow | block | reduce
  onchain, onchain_gate,                   // Camada D já existe, ver seção 1
  glassnode, glassnode_gate,               // idem, quando o gate do Glassnode for portado
  video_rule: { ok, vol_break, max_pb, vol_entry, messy }
}
```

Composição (E lógico de vetos), só quando as flags estiverem ligadas:
```
go = video_rule.ok
  && !messy
  && book_status permite o lado          // bias alinhado, não NEUTRAL, confidence >= 50
  && sentiment_gate != block             // se FORGE_SENTIMENT_GATE=on
  && onchain_gate   != block             // se FORGE_ONCHAIN_GATE=on
  && glassnode_gate != block             // se GLASSNODE_GATE=on
```

`reduce` não bloqueia — reduz o tamanho do lote (ex.: 10% da banca →
5%). Sizing é responsabilidade do app, não do motor de score.

**Semáforo do book (Camada B, já existe hoje)**:
```
bias BEARISH  → libera short, bloqueia long
bias BULLISH  → libera long,  bloqueia short
bias NEUTRAL  → não opera
confidence < 50 → não opera        // < ~1.5 de 3 exchanges conectadas
```

---

## 4. O que NÃO fazer (recorte relevante pra Camada A/F/composição)

1. Usar `liquidity_score` como qualidade do trade — é agitação do book.
2. Renomear `confidence` pra "probabilidade de acerto" — é cobertura de exchanges.
3. Somar Donchian + SuperTrend + SMA21 no mesmo alerta.
4. RVOL vs SMA20 como substituto da regra de volume verde vs vermelho — não é a mesma coisa.
5. SMA200 como suporte/resistência obrigatória — não é o operacional da mão.
6. Fear & Greed no clique de 30m — peso zero, só card informativo (já é assim no bloco `sentiment` do Forge).
7. Otimizar pesos com poucas dezenas de trades — qualquer research fica pra depois de log com PnL real.
8. Mudar templates FinanceX Normal/Elite por baixo — filtros novos são gates, não rewrite da estratégia.

---

## 5. Ordem sugerida (retomando do que já está pronto)

1. ~~Logger~~ → **fazer agora**: colunas novas + gravar block também.
2. **Regra do vídeo (Camada A)** no app de alertas — sozinha já muda o operacional.
3. ~~`GET /sentiment/{symbol}` + bloco em `/signal`~~ → **já pronto**, é só consumir.
4. ~~Camada D (on-chain público)~~ → **já pronto**, é só consumir.
5. ~~Glassnode~~ → **já pronto e calibrado** (perfis de peso, gate assimétrico, `close_time`).
6. `avaliarForgeDirecao` passa a devolver os três gates **sem** alterar `status` antigo, até ligar as flags.
7. Cron 30m de snapshot pra todos os símbolos.
8. Research walk-forward só depois de ≥8 semanas de log com PnL.

Ligar as flags nesta ordem, uma por semana, medindo o PF do long:
`VIDEO_VOLUME_RULE` → `MESSY_SKIP` → `FORGE_SENTIMENT_GATE` → `GLASSNODE_GATE` → `FORGE_ONCHAIN_GATE`.

---

## 6. Perguntas em aberto (só quem está no app principal decide)

- O trader pode ter mais de uma estratégia ativa ao mesmo tempo, ou é uma só por vez?
- Insight/alerta de bloqueio aparece automaticamente (notificação) ou só quando o usuário entra na aba?
- `avaliarForgeDirecao` já existe hoje no app principal com essa assinatura, ou precisa ser criado do zero?
- Onde mora `book_status` hoje — é o `bias`/`confidence` puro do Forge, ou já passa por alguma camada intermediária no app principal?
