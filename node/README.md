# Forge Heatmap Multiexchange — Node.js (fase de teste)

Implementação Node.js do Forge, isolada do protótipo Python que vive em
`../` (fora desta pasta) — nenhum dos dois mexe no código do outro.

**Escopo desta fase:** **Binance, OKX, Bybit e Bitget** (94 símbolos —
veja `src/normalizer/symbols.js`), dados públicos de mercado: order book,
trades, open interest, funding rate e liquidações (onde a exchange expõe
de forma direta — ver "Limitações conhecidas"). Sem API keys privadas,
sem execução de ordens.

```
Exchange WS/REST → Adapter → Normalizer (schema validado com zod) →
  Liquidity Engine + histórico (OI/liquidações/heatmap) → Score Engine → API HTTP
```

## Rodar localmente

Requer Node.js 20+.

```bash
npm install
npm run dev     # com --watch, recarrega ao salvar
# ou
npm start
```

```bash
curl http://localhost:3000/health
curl http://localhost:3000/api/market/BTCUSDT
curl http://localhost:3000/api/score/BTCUSDT
```

## Testes

```bash
npm test
```

20 testes (`node --test`, sem dependência extra de test runner) cobrindo:
normalização de símbolos, conversão para notional USD, ordenação/trim do
order book local, detecção de gap de sequência (Binance `pu`/`u`),
reconexão automática após o servidor fechar o socket, imbalance do order
book, e as respostas de `/health` e `/api/market/:symbol`.

## Variáveis de ambiente (todas não sensíveis)

| Variável | Padrão | Descrição |
|---|---|---|
| `PORT` | `3000` | Porta do servidor HTTP |
| `SYMBOLS` | todos os 94 símbolos de `src/normalizer/symbols.js` | Lista separada por vírgula pra rastrear só um subconjunto |
| `REGION` | `default` | Rótulo informativo, não afeta roteamento ainda |
| `ORDER_BOOK_DEPTH` | `50` | Níveis de bid/ask mantidos por símbolo/exchange |
| `MAX_TRADES_PER_SYMBOL` | `2000` | Cap do buffer de trades recentes por símbolo |
| `LOG_LEVEL` | `info` | `error` \| `warn` \| `info` \| `debug` |
| `SIGNAL_MIN_CONFIDENCE` | `60` | Limiar de `confidence` usado no campo `signalReady` de `/api/score/:symbol` |
| `GLASSNODE_API_KEY` | vazio | Chave da API Glassnode pro bloco `glassnode` em `/api/score/:symbol`. Sem chave, o pipeline de mercado continua 100% funcional — só `glassnode.has_key` vem `false` |
| `FORGE_SENTIMENT_PROFILE` | `30m` | Perfil de peso do bloco `glassnode`: `30m` \| `2h` \| `daily` (`2h`/`daily` usam a mesma tabela) |
| `GLASSNODE_GATE` | `off` | Liga `evaluateGlassnodeGate(...)` a devolver `block`/`reduce` de verdade — desligado, sempre `allow` |
| `FORGE_SENTIMENT_GATE` | `off` | Idem, pro `evaluateSentimentGate(...)` do bloco `sentiment` |
| `FORGE_ONCHAIN_GATE` | `off` | Idem, pro `evaluateOnchainGate(...)` do bloco `onchain` |

Nenhuma API key de exchange é lida de env var — o pipeline de mercado
(order book/trades/OI/funding/liquidações) inteiro usa apenas endpoints
públicos. `GLASSNODE_API_KEY` é a única exceção, opcional, só pro bloco
de sentimento on-chain via Glassnode descrito abaixo — os blocos
`sentiment` e `onchain` não usam chave nenhuma.

## Endpoints

- `GET /health` — status do processo (uptime) + estado de conexão de cada
  exchange (`connected`, `lastMessageAgeMs`).
- `GET /api/market/:symbol` — estado normalizado atual: mid price,
  exchanges conectadas, imbalance do order book, maiores paredes de
  liquidez, contagem de trades recentes.
- `GET /api/score/:symbol` — `{ hasEnoughData: false, reason }` se ainda
  não há order book para o símbolo, ou o `LIQUIDITY_SCORE` completo com
  `liquidityScore`, `bias`, `confidence`, `fundingRate`, `oiChangePct`,
  `liquidationNotionalUsd`, o detalhamento por componente e
  `signalReady`/`minConfidenceRequired` (ver `SIGNAL_MIN_CONFIDENCE`
  abaixo) — sempre acompanhado de três blocos irmãos add-only,
  independente de `hasEnoughData`: `glassnode`, `sentiment` e `onchain`
  (ver seções abaixo).
- `GET /api/sentiment/:symbol` — só o bloco `sentiment`, isolado.
  Aceita **qualquer** símbolo (não precisa estar em `SYMBOLS`) — só
  perde `liq_side`, que depende de liquidações locais.
- `GET /api/symbols` — lista de símbolos rastreados nesta instância.
- `GET /api/diagnostics/binance` — estado de sincronização do order book
  por símbolo na Binance (útil pra depurar rate-limit sem acesso a logs).

O `LIQUIDITY_SCORE` segue os pesos da seção 7 do PDF de arquitetura:
concentração de liquidez 25%, remoção de liquidez 15%, open interest 15%,
liquidações 15%, imbalance do order book 10%, CVD 10%, funding rate 5%,
confirmação entre exchanges 5% (mínimo de 3 das 4 exchanges conectadas
pra confiança plena — ver `MIN_EXCHANGES_FOR_FULL_CONFIDENCE`). A
implementação espelha `forge/engine/score_engine.py` (o protótipo
Python) componente a componente.

`signalReady` em `/api/score/:symbol` é `confidence >= SIGNAL_MIN_CONFIDENCE`
(env var, default `60`) — um atalho pronto pra quem consome o endpoint
não precisar hardcodar o próprio limiar; `minConfidenceRequired` devolve
o valor usado, caso o consumidor prefira aplicar a própria lógica sobre
o `confidence` bruto.

## Sentimento on-chain (Glassnode) — bloco add-only, calibrado

`src/engine/glassnodeSentiment.js` + `src/engine/glassnodeClient.js`
calculam um `glassnode_score` (-100..+100) a partir de 8 métricas
Glassnode (SOPR, STH-SOPR, MVRV, STH-MVRV, NUPL, exchange netflow,
variação 24h da reserva em exchange, variação 7d do supply de
stablecoins), ancoradas em BTC pra qualquer símbolo que não seja
BTCUSDT/ETHUSDT direto. Puramente aditivo — nunca participa de
`liquidityScore`/`bias`/`confidence`. Objeto irmão `glassnode` em
`/api/score/:symbol`, mesmo formato (snake_case) que o Python devolve
em `/signal/{symbol}`.

**Convenção de sinal**: positivo = RISK_ON = acumulação / reserva
saindo da exchange / **gasto no prejuízo** (capitulação é tratada como
sinal contrarian de acumulação, não como medo).

Agregação por **média ponderada** (não simples), dois perfis via
`FORGE_SENTIMENT_PROFILE=30m|2h|daily` (default `30m`; `2h`/`daily`
usam a mesma tabela), pesos renormalizados entre os componentes
disponíveis. `notes` ganha frases automáticas (`"sopr: profit taking"`,
`"sopr: capitulation spend"`, `"mvrv: euphoria"`, `"mvrv: fear"`).

`evaluateGlassnodeGate(components, glassnodeScore, glassnodeConfidence, side)`
— função pura, não chamada automaticamente, gated por `GLASSNODE_GATE`
(default off). Regras assimétricas: `LONG` bloqueia em duas condições
independentes (score ≤ -12, ou `sopr`/`sth_mvrv`/`mvrv`/`netflow` de
distribuição/euforia), `SHORT` só numa (score ≥ +28, ou `sth_sopr`
baixo + netflow alto) — o backtest tolera short bem melhor que long.
`computeGlassnodeSentiment` aceita um `closeTime` opcional (unix
seconds) pra leitura sem lookahead — não usado por `/api/score`, existe
pro app de alertas passar o `closeTime` real do sinal.

Sem `GLASSNODE_API_KEY`, `glassnode.has_key` vem `false` e todos os
componentes vêm `avail: false` — o resto do payload não é afetado.

## Sentimento de derivativos — bloco add-only

`src/engine/sentimentEngine.js` + `src/engine/sentimentClient.js`, sem
chave nenhuma (só endpoints públicos da Binance + Fear & Greed). 9
componentes: `funding_z`, `basis_bps`, `retail_ls`, `whale_pos_ls`,
`taker_15m`, `taker_shift`, `oi_price_agree`, `liq_side` (reaproveita
as liquidações já ingeridas em `MarketState`, com `side` — não
reconsulta outra fonte) e `fng` (Fear & Greed, só informativo, peso
**zero** no agregado). Normalizados -100..+100, agregados (exceto
`fng`) em `sentiment_score`/`sentiment_bias`/`sentiment_confidence`.
Toda chamada pra um alt também calcula `btc_anchor: { score, bias }`.

`evaluateSentimentGate(sentimentScore, sentimentConfidence, side)` —
função pura, não automática, gated por `FORGE_SENTIMENT_GATE` (default
off).

## On-chain público — bloco add-only

`src/engine/onchainEngine.js` + `src/engine/onchainClient.js`, sem
chave nenhuma (mempool.space + DefiLlama). 7 componentes: `btc_fee`,
`btc_mempool`, `btc_hashrate` (congestionamento/segurança da rede
Bitcoin, sempre calculados), `chain_tvl_1d`, `eth_gas` (só pra
ETH/Arbitrum/Optimism/Solana/Sui/Avalanche/BSC — BTC e meme coins usam
só a camada global), `stables_7d` e `peg_stress` (desvio de USDT/USDC
de US$ 1 — acima de 50 bps força `onchain_bias: RISK_OFF`
independente do agregado). Pesos fixos, renormalizados entre os
componentes disponíveis.

`evaluateOnchainGate(bias, pegStressed, confidence, side)` — função
pura, não automática, gated por `FORGE_ONCHAIN_GATE` (default off); a
única regra explícita do briefing (`peg stress → block LONG`) está
implementada.

**Todos os três blocos** (`glassnode`, `sentiment`, `onchain`) e suas
respectivas funções `evaluate*Gate` degradam pra `avail:false`/`allow`
sem nunca lançar exceção nem derrubar `/api/score` — testado com as
fontes de rede indisponíveis.

## Como adicionar uma exchange

1. Criar `src/exchanges/<nome>/<Nome>Adapter.js` estendendo
   `ExchangeAdapter` (`src/exchanges/base/ExchangeAdapter.js`) e
   implementando `getWsUrl()`, `getSubscribeMessages()` (se aplicável) e
   `handleMessage(raw)`.
2. Adicionar o mapeamento de símbolo em `src/normalizer/symbols.js`.
3. Emitir eventos `orderbook`/`trade` já validados pelo schema
   (`src/normalizer/validate.js`). Opcionalmente, também `openInterest`/
   `funding` (implementando `restPollOnce()` + `this.restPollIntervalMs`
   — a classe base já cuida do loop) e `liquidation` (via WS, se a
   exchange expuser o canal).
4. Registrar a nova instância em `src/index.js` (array `adapters`).

## Limitações conhecidas

- Liquidações: implementadas para Binance (`<symbol>@forceOrder`), Bybit
  (`allLiquidation.<symbol>`) e OKX (`liquidation-orders`, uma inscrição
  cobre todos os símbolos SWAP). Bitget não tem esse canal cabeado ainda
  (o protótipo Python também não implementou lá) — sem dado de
  liquidação da Bitget, esse componente do score cai naturalmente para 0
  quando as outras três também não têm liquidação recente.
- `next_funding_time` da Bitget fica em 0 — o endpoint usado
  (`current-fund-rate`/`tickers`) não expõe esse campo, herdado do mesmo
  caveat do protótipo Python.
- OKX, Bybit e Bitget não expõem sequência por mensagem no canal de book
  como a Binance; a detecção de duplicidade/gap hoje é forte só no
  adapter da Binance (via `pu`/`u`). Checksum de integridade do book das
  outras três ainda não é validado.
- BONK e PEPE só existem na Binance/Bybit sob ticker escalado 1000x
  (`1000BONKUSDT`/`1000PEPEUSDT`) — deliberadamente não mapeado, ficam só
  nas exchanges que os listam a 1x (OKX/Bitget) pra não precisar de um
  caminho de reescala de preço à parte.
- Com 94 símbolos em 4 exchanges, o uso de CPU/memória é bem maior que a
  fase de 2 símbolos original — em instância free/nano de plataforma
  gerenciada, vale monitorar se não estoura os limites de recurso.
- Sem persistência: todo o estado é em memória e reinicia com o
  processo (esperado para uma API stateless em plataforma gerenciada).
- Rate limit da Binance: o snapshot REST inicial do order book
  (`GET /fapi/v1/depth`, peso 20) pode ser temporariamente rejeitado
  (`429`/`-1003`) se a IP já tiver usado boa parte do budget de
  2400/min por outro motivo. O adapter já trata isso com backoff de 5s
  e re-tenta sozinho sem intervenção — não é preciso reiniciar o
  processo.

## Deploy (Koyeb / Render)

Sem SSH, sem arquivo local persistente — build via `Dockerfile` nesta
pasta:

```bash
docker build -t forge-heatmap-node .
docker run -p 3000:3000 -e PORT=3000 forge-heatmap-node
```

Na plataforma gerenciada: aponte para este diretório (`node/`) como raiz
do build, defina `PORT` (a maioria das plataformas injeta automaticamente),
e o `Dockerfile` cuida do resto. O processo escuta em `0.0.0.0`, roda com
usuário não-root, e trata `SIGTERM`/`SIGINT` para desligar graciosamente
(fecha o servidor HTTP e as conexões WebSocket antes de sair) — compatível
com o ciclo de restart/scale-down de Koyeb e Render.

Nenhum deploy foi feito automaticamente — isso fica para quando você
confirmar.
