# Forge — Heatmap Multiexchange

Módulo independente de inteligência de mercado: agrega order book, trades,
open interest, funding e liquidações da Binance, OKX, Bybit e Bitget
(Fase 1), normaliza tudo em notional USD (Fase 2), calcula um heatmap de
liquidez agregado (Fase 2) e um `LIQUIDITY_SCORE` de 0–100 (Fases 3–4),
seguindo `Forge_Heatmap_Multiexchange_Architecture.pdf`.

Fases 5 (Gate.io, KuCoin, MEXC, BingX, BitMart, HTX, CoinEx) e 6
(backtest/validação antes de permitir que o score altere entradas/saídas
automaticamente) ainda não estão implementadas.

Pra integrar outro app com esse backend via HTTP (conexões, estratégia,
trades, insights), veja [`API.md`](API.md) — lista todos os endpoints com
exemplos de request/resposta — e
[`INTEGRACAO_APP_PRINCIPAL.md`](INTEGRACAO_APP_PRINCIPAL.md), documento
de handoff com o fluxo recomendado e os pontos de atenção pra quem for
implementar o lado consumidor.

## Arquitetura

```
Exchange WS/REST → Adapters (isolados) → Normalizer → LiquidityEngine
                 → SymbolMarketState (score) → Heatmap.get_signal() → Bot
```

- `forge/adapters/`: um adapter por exchange, cada um com seu próprio loop
  de WebSocket (reconectando com backoff) e polling REST (funding/OI),
  para que uma mudança de API numa exchange não derrube as demais.
- `forge/engine/local_book.py`: livro de ofertas local genérico
  (snapshot + delta) reusado por todos os adapters.
- `forge/engine/liquidity_engine.py`: agrega os livros de todas as
  exchanges por símbolo em buckets de preço, em notional USD.
- `forge/engine/score_engine.py`: estado contínuo por símbolo (histórico
  de heatmap, OI, funding, trades, liquidações) e cálculo do
  `LIQUIDITY_SCORE` com os pesos da seção 7 do PDF.
- `forge/interface.py`: `Heatmap.get_signal(symbol)` — a interface que o
  bot consome.
- `forge/app.py`: liga tudo e expõe uma API HTTP (`GET /signal/{symbol}`)
  para que o bot (mesmo se não for Python — ex.: um EA em MQL5) consiga
  consumir o sinal via requisição HTTP simples.
- `forge/engine/glassnode_client.py` + `forge/engine/glassnode_sentiment.py`:
  bloco **add-only** de sentimento on-chain (Glassnode) — SOPR, MVRV,
  NUPL, netflow/reserva de exchange e supply de stablecoins, viram um
  `glassnode_score` (-100..+100) exposto como objeto irmão `glassnode`
  dentro de `/signal/{symbol}`. Nunca participa do `liquidity_score`,
  do `bias` nem da `confidence` de confirmação entre exchanges — ver
  seção "Sentimento on-chain" abaixo.
- `forge/engine/sentiment_client.py` + `forge/engine/sentiment_engine.py`:
  bloco **add-only** de sentimento de derivativos (funding, basis,
  long/short retail e whale, taker flow, OI vs preço, liquidações com
  lado, Fear & Greed) — só dados públicos da Binance, sem chave. Vira
  `sentiment_score` (-100..+100) em `GET /sentiment/{symbol}` e como
  objeto irmão `sentiment` dentro de `/signal/{symbol}`. Mesma regra:
  nunca participa do `liquidity_score` — ver seção "Sentimento de
  derivativos" abaixo.
- `forge/engine/onchain_client.py` + `forge/engine/onchain_engine.py`:
  bloco **add-only** de on-chain público (mempool.space + DefiLlama) —
  fee/mempool/hashrate do Bitcoin, TVL da chain do alt, supply
  agregado de stablecoins e estresse de peg (USDT/USDC). Sem chave
  nenhuma. Vira `onchain_score` (-100..+100) como objeto irmão
  `onchain` dentro de `/signal/{symbol}`. Mesma regra: nunca participa
  do `liquidity_score` — ver seção "On-chain público" abaixo.
- `forge/accounts/`: primeiro passo do roadmap do FinanceX FORGE
  (`FinanceX_FORGE_Master_Technical_Blueprint.pdf`, etapa "02 Exchange
  Integration") — conexões privadas por usuário (API key/secret) para
  ler saldo, posições e ordens abertas em Binance/Bybit/Bitget/OKX. Um
  `PrivateExchangeClient` por exchange (mesmo princípio de isolamento dos
  adapters públicos), segredos cifrados em repouso (SQLite +
  `cryptography.Fernet`) e nunca devolvidos nas respostas da API. Não
  implementa nenhum endpoint de trading ou saque — apenas leitura.
- `forge/strategies/`: seleção de estratégia por usuário — escrever a
  própria (texto livre) ou ativar um template FinanceX (Normal/Elite).
  Só uma estratégia fica `ACTIVE` por vez; ativar uma nova arquiva a
  anterior. Sem Strategy DSL/backtest ainda (blueprint seção 15-18) — a
  IA não estrutura a descrição livre em regras mensuráveis nesta versão.
- `forge/ledger/`: Trading Ledger normalizado (blueprint seção 9-10).
  `POST /accounts/connections/{id}/sync-trades` busca os fills/execuções
  mais recentes da exchange (via os mesmos `PrivateExchangeClient` de
  `forge/accounts/`, agora com `get_recent_trades()`), grava como `Trade`
  (dedup por `(exchange, external_id)`, então repetir a sincronização é
  seguro) e vincula cada trade novo à estratégia `ACTIVE` do usuário, se
  houver. Sem histórico completo/paginação ainda — só a janela recente
  que cada exchange devolve por padrão (3 dias na OKX, por exemplo).
  `classification` fica sempre `UNKNOWN`: o Adherence Engine que avaliaria
  aderência de verdade (blueprint seção 20) não existe nesta versão.
- `forge/insights/`: motor de análise comportamental sob demanda
  (`FORGE Modulo Comportamental e Estrategia Spec.pdf`, seção 2).
  `POST /insights/generate?user_id=` calcula, na hora, a partir dos
  trades já sincronizados: performance por origem de estratégia
  (`strategy_trades.origin`) e consistência por horário do dia (UTC).
  Exige no mínimo 15 trades por categoria — abaixo disso, devolve
  explicitamente "dados insuficientes" em vez de inventar um padrão
  (mesma regra da seção 2.5 do spec / seção 46 do blueprint). Frases são
  geradas por template, não por IA — sem chave da Anthropic configurada
  ainda. Sem jobs automáticos (diário/semanal/mensal) nem a aba de
  Perguntas Sugestivas — ambos exigem infraestrutura que este app ainda
  não tem (agendador, integração com Claude API) e ficam para uma
  próxima rodada.

## Segurança

Todo o pipeline de mercado usa **apenas dados públicos** — nenhuma API key
é necessária para order book, trades, OI, funding ou liquidações. O
pipeline de mercado (order book/trades/OI/funding/liquidações,
`glassnode`/`sentiment`/`onchain`) nunca guarda chave de exchange
nenhuma.

`forge/accounts/` (conexões privadas) é diferente: guarda API key/secret
do usuário cifrados com `Fernet` (chave em `FORGE_ENCRYPTION_KEY`, nunca
no repositório — veja `.env.example`). Nenhuma chave/secret é devolvida
por qualquer endpoint.

**Autenticação por Bearer token** (`forge/auth.py`): se `FORGE_API_KEY`
estiver definida no ambiente, todo endpoint exceto `GET /health` e
`GET /signal/{symbol}` exige o header `Authorization: Bearer
<FORGE_API_KEY>` — sem isso, `401`. `user_id` continua sendo texto livre
*dentro* desse espaço autenticado (não é uma identidade verificada, só
particiona os dados). **Sem `FORGE_API_KEY` definida, não há
autenticação nenhuma** — aceitável só para desenvolvimento local; **não
exponha a porta 8080 publicamente sem definir essa chave primeiro** — a
mesma recomendação de firewall abaixo vale em dobro aqui, já que agora
há segredos reais em jogo, não só dados públicos de mercado. O painel de
teste (`/dashboard`) tem um campo pra colar a chave manualmente — ela
nunca é embutida na página servida, pra não vazar pra quem só carregar a
URL.

## Rodar o dashboard rapidamente (Windows)

Depois de fazer o setup uma vez (seção abaixo), dê duplo-clique em
`run_dashboard.bat` — ele sobe o servidor e abre
`http://localhost:8080/dashboard` sozinho, carregando `FORGE_DB_PATH` e
`FORGE_ENCRYPTION_KEY` do `.env`. Feche a janela do terminal que abre
junto para parar o servidor. O `.env` guarda sua chave de criptografia
real — nunca o compartilhe nem o commite (já está no `.gitignore`).

`GLASSNODE_API_KEY` (env var, opcional) é mais uma exceção, só pro
bloco de sentimento on-chain descrito abaixo — sem ela o resto do
serviço continua 100% funcional, só o bloco `glassnode` vem com
`has_key: false`.

## Rodar localmente

Requer Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # e preencha FORGE_ENCRYPTION_KEY (veja o arquivo)
python -m forge.app
```

`FORGE_ENCRYPTION_KEY` só é obrigatória para usar `/accounts/*` (criar ou
ler conexões de exchange privadas) — o heatmap público (`/signal/{symbol}`)
funciona sem ela.

Depois:

```bash
curl http://localhost:8080/signal/BTCUSDT
```

## Sentimento on-chain (Glassnode) — bloco add-only

Opcional. Com `GLASSNODE_API_KEY` setada no ambiente, `/signal/{symbol}`
passa a incluir um objeto irmão `glassnode`:

```bash
export GLASSNODE_API_KEY=sua_chave
python -m forge.app
curl http://localhost:8080/signal/BTCUSDT | jq .glassnode
```

8 componentes (SOPR, STH-SOPR, MVRV, STH-MVRV, NUPL, exchange netflow,
variação 24h da reserva em exchange, variação 7d do supply de
stablecoins), cada um normalizado -100..+100, agregados por **média
ponderada** (não simples) em `glassnode_score` / `glassnode_bias`
(`RISK_ON`/`RISK_OFF`/`NEUTRAL`, limiar ±15) / `glassnode_confidence`.

**Convenção de sinal (calibrada, não é a leitura ingênua)**: positivo =
RISK_ON = acumulação / reserva saindo da exchange / **gasto no
prejuízo** (capitulação é tratada como sinal contrarian de acumulação,
não como medo) — cuidado ao "consertar" os sinais das fórmulas em
`glassnode_sentiment.py` sem reler essa convenção.

Dois perfis de peso, selecionados por `FORGE_SENTIMENT_PROFILE=30m|2h|daily`
(default `30m`, `2h`/`daily` usam a mesma tabela — "perfil de regime"):

| Componente | 30m | 2h/daily |
|---|---|---|
| `exch_netflow` | 0.26 | 0.16 |
| `sth_sopr` | 0.22 | 0.14 |
| `exch_reserve_d1` | 0.14 | 0.10 |
| `sth_mvrv` | 0.14 | 0.10 |
| `sopr` | 0.10 | 0.14 |
| `mvrv` | 0.06 | 0.18 |
| `nupl` | 0.05 | 0.14 |
| `stables` | 0.03 | 0.04 |

Pesos renormalizados entre os componentes disponíveis. `notes` ganha
frases automáticas em limiares específicos (`"sopr: profit taking"`,
`"sopr: capitulation spend"`, `"mvrv: euphoria"`, `"mvrv: fear"`).

Símbolos que não sejam BTCUSDT/ETHUSDT ancoram na camada BTC
(`asset_used: "BTC"`, `asset_direct: false`) em vez de escanear o
catálogo Glassnode em runtime. Sem chave, ou com chave inválida,
`has_key` vem `false` e todos os componentes vêm `avail: false` — o
endpoint continua respondendo 200 normalmente, nada mais no payload é
afetado.

`forge/engine/glassnode_sentiment.py` também exporta
`evaluate_glassnode_gate(components, glassnode_score, glassnode_confidence, side)`
— função pura, não chamada automaticamente, gated por `GLASSNODE_GATE`
(default off). Implementa as regras **assimétricas** do briefing: o
backtest tolera short bem melhor que long, então `LONG` tem duas
condições independentes de bloqueio (score ≤ -12, ou a combinação
`sopr`/`sth_mvrv`/`mvrv`/`netflow` de distribuição/euforia) enquanto
`SHORT` só tem uma (score ≥ +28, ou `sth_sopr` baixo + netflow alto).
Também aceita um `close_time` opcional em `compute_glassnode_sentiment`
pra leitura sem lookahead (só usa pontos com `t <= close_time`) — não é
usado por `/signal` (que não tem conceito de "alerta"), existe pra
quando o app de alertas passar o `closeTime` real do sinal.

O serviço Node (`node/`) expõe a mesma versão calibrada — perfis de
peso, fórmulas, gate assimétrico e `closeTime` — em
`GET /api/score/:symbol`, mesmo formato. Ver `node/README.md`.

## Sentimento de derivativos — bloco add-only

Sem chave nenhuma (só endpoints públicos da Binance + Fear & Greed):

```bash
curl http://localhost:8080/sentiment/BTCUSDT
```

9 componentes: `funding_z` (funding rate vs média/desvio das últimas 21
taxas), `basis_bps` (prêmio do futuro sobre o índice), `retail_ls` e
`whale_pos_ls` (razão long/short de conta e de posição), `taker_15m` e
`taker_shift` (fluxo agressor 15m e sua mudança vs 1h), `oi_price_agree`
(OI e preço andando juntos ou não), `liq_side` (mais notional
liquidado no lado comprado ou vendido — reaproveita as liquidações já
ingeridas pelo `SymbolMarketState`, com `side`, em vez de reconsultar
outra fonte) e `fng` (Fear & Greed — só informativo, peso **zero** no
agregado). Cada um normalizado -100..+100 e agregados (exceto `fng`) em
`sentiment_score` / `sentiment_bias` (`RISK_ON`/`RISK_OFF`/`NEUTRAL`,
limiar ±15) / `sentiment_confidence`. Toda chamada pra um alt também
calcula um `btc_anchor: { score, bias }` — com nota se o alt e o BTC
discordarem de sinal.

`GET /sentiment/{symbol}` aceita **qualquer** símbolo (não precisa
estar entre os `SYMBOLS` rastreados por este processo — só perde o
`liq_side`, que depende de liquidações locais). O mesmo bloco também
aparece como objeto irmão `sentiment` dentro de `/signal/{symbol}`.
Fonte fora do ar = componente `avail: false`, nunca HTTP 500.

`forge/engine/sentiment_engine.py` também exporta
`evaluate_sentiment_gate(score, confidence, side)` — uma função pura
(`LONG`/`SHORT` → `allow`/`block`/`reduce`) pra quem já sabe o lado da
operação (o app de alertas) chamar; ela **não** é chamada
automaticamente por `/sentiment` nem `/signal`, e com
`FORGE_SENTIMENT_GATE` desligada (padrão) sempre devolve `allow`.

O serviço Node (`node/`) expõe o mesmo bloco em
`GET /api/sentiment/:symbol` e como objeto irmão `sentiment` em
`GET /api/score/:symbol` — ver `node/README.md`.

## On-chain público — bloco add-only

Sem chave nenhuma (mempool.space + DefiLlama):

```bash
curl http://localhost:8080/signal/BTCUSDT | jq .onchain
```

7 componentes: `btc_fee` e `btc_mempool` (congestionamento da rede
Bitcoin — fee recomendada e tamanho do mempool), `btc_hashrate`
(variação 3d), `chain_tvl_1d` (variação 24h do TVL da chain do alt —
ETH, Arbitrum, Optimism, Solana, Sui, Avalanche, BSC; BTC e "meme
coins" como DOGE/PEPE/BONK não têm chain própria de TVL, então esse
componente e `eth_gas` ficam `avail: false` e só a camada global
conta), `eth_gas` (gas price via RPC público, sem chave Etherscan),
`stables_7d` (variação 7d do supply agregado de stablecoins) e
`peg_stress` (desvio de USDT/USDC de US$ 1 — acima de 50 bps força
`onchain_bias: RISK_OFF` e liga a nota `"stable peg stress"`,
independente do agregado ponderado). Pesos fixos (perfil 30m,
renormalizados entre os componentes disponíveis):
`stables_7d 0.22, chain_tvl_1d 0.18, btc_fee 0.16, btc_mempool 0.14,
peg_stress 0.14, eth_gas 0.10, btc_hashrate 0.06`.

Sem mapeamento pra chain (BTC, meme coins) ou fonte fora do ar =
componente `avail: false`, nunca HTTP 500. `forge/engine/onchain_engine.py`
também exporta `evaluate_onchain_gate(bias, peg_stressed, confidence, side)`,
mesmo padrão do gate de sentimento: função pura, não chamada
automaticamente, com `FORGE_ONCHAIN_GATE` desligada (padrão) sempre
`allow`. A única regra explícita do briefing (`peg stress → block
LONG`) está implementada; o resto (`reduce` em `NEUTRAL`) segue o
mesmo padrão do gate de sentimento por consistência.

O serviço Node (`node/`) expõe o mesmo bloco `onchain` em
`GET /api/score/:symbol` — ver `node/README.md`.

## Testes

```bash
pytest
```

## Deploy na VPS

1. Copie o repositório para a VPS (`git clone`/`rsync`/`scp`) em qualquer
   diretório temporário.
2. Rode `bash deploy/deploy.sh` de dentro do repo copiado — instala
   Python, cria venv, instala dependências e registra o serviço systemd
   `forge-heatmap` em `/opt/forge-heatmap`.
3. `sudo systemctl status forge-heatmap` / `sudo journalctl -u forge-heatmap -f`
   para acompanhar.
4. `curl http://<ip-da-vps>:8080/health` e
   `curl http://<ip-da-vps>:8080/signal/BTCUSDT` para validar dados reais
   chegando das 4 exchanges.

Se for expor a porta 8080 publicamente, restrinja por firewall
(`ufw allow from <seu-ip> to any port 8080`) **e defina `FORGE_API_KEY`**
— sem essa variável, a API não tem autenticação nenhuma (ver seção
"Segurança").

## Deploy no Render

O repositório já tem um `render.yaml` (Blueprint) pronto — o Render lê
esse arquivo automaticamente ao conectar o repo.

**Antes de começar**, duas decisões que o `render.yaml` já assume:
- **Plano pago (Starter ou acima), nunca o free tier** — o free hiberna
  depois de ~15min sem tráfego HTTP, o que derrubaria as conexões
  WebSocket contínuas com as 4 exchanges (o coração do heatmap).
- **Persistent Disk** — sem isso, o SQLite (`forge_accounts.db`,
  conexões/estratégias/trades/insights) some a cada deploy. Já vem
  configurado no `render.yaml` (1GB em `/var/data`, ajuste o tamanho se
  precisar).

Passos:
1. No dashboard do Render: **New → Blueprint**, conecte este repositório
   Git. Ele detecta o `render.yaml` sozinho.
2. Antes do primeiro deploy, preencha manualmente no dashboard (o
   `render.yaml` deixa essas duas como `sync: false` de propósito, pra
   nunca ficarem no código):
   - `FORGE_ENCRYPTION_KEY` — gere uma nova, não reaproveite a local:
     `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - `FORGE_API_KEY` — gere uma nova também:
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`
3. Deploy. O Render entrega HTTPS automaticamente — não precisa de
   proxy/certificado próprio.
4. `curl https://<seu-app>.onrender.com/health` pra confirmar, e teste
   `POST /accounts/connections` com o header `Authorization: Bearer
   <FORGE_API_KEY>` que você definiu no passo 2.

**Chaves novas = banco vazio.** Como o Persistent Disk do Render é um
disco físico diferente do arquivo local, a conexão OKX que você já tem
localmente não aparece automaticamente lá — reconecte pelo dashboard
(`/dashboard`) ou pela API depois do deploy. Se preferir migrar os dados
existentes em vez de recomeçar, use o Shell do Render (dashboard → seu
serviço → Shell) pra copiar o `forge_accounts.db` local pro disco
montado — nesse caso reaproveite a mesma `FORGE_ENCRYPTION_KEY` local,
senão os segredos cifrados ficam ilegíveis.

Pra habilitar o bloco de sentimento on-chain em produção, adicione a
`GLASSNODE_API_KEY` ao serviço sem colocá-la no repositório — por
exemplo `sudo systemctl edit forge-heatmap` e um drop-in com
`Environment=GLASSNODE_API_KEY=sua_chave`, ou um `EnvironmentFile=`
apontando pra um arquivo fora do repo com permissão restrita ao usuário
`forge`.

## Observações técnicas (herdadas do PDF, seção 12)

Endpoints, limites e formato de payload podem mudar por exchange. Os
adapters foram escritos a partir da documentação pública de cada
exchange, mas **devem ser validados contra a documentação oficial vigente
antes de qualquer decisão de mercado real** — em especial:

- `next_funding_time` do Bitget está zerado (endpoint usado não o expõe;
  seria necessário confirmar o endpoint correto).
- Cálculo de OI em USD via mid-price local (OKX/Bitget) é uma
  aproximação quando o payload não traz o valor em USD diretamente.

## Validado em teste ao vivo (2026-08-13)

Rodado localmente contra as 4 exchanges reais. Dois bugs só visíveis com
tráfego real foram encontrados e corrigidos:

- **Binance**: o adapter disparava uma nova chamada REST de snapshot do
  order book a cada evento de depth (~every 100ms) enquanto não
  sincronizado, estourando o rate limit e derrubando a conexão em loop.
  Corrigido com lock de "sync em andamento" + backoff de 5s entre
  tentativas. Efeito colateral do bug original: a IP de teste tomou ban
  temporário da Binance (`code -1003`) por algumas horas — o serviço
  continua funcional (WS de order book/trades não é afetado) e volta a
  buscar funding/OI automaticamente quando o ban expira.
- **Bybit**: o tópico `liquidation.<symbol>` está obsoleto — a Bybit
  renomeou para `allLiquidation.<symbol>` (payload também mudou: lista de
  entradas com campos `s/S/p/v/T` em vez de um objeto único). Inscrever no
  tópico antigo não gera erro, mas faz o servidor parar de enviar
  **qualquer** dado (nem order book, nem trades) na conexão — corrigido.

Depois das correções, Bybit/OKX/Bitget ficaram estáveis (sem reconexões)
produzindo `liquidity_score`/`bias`/`confidence` coerentes para BTCUSDT e
ETHUSDT via `GET /signal/{symbol}`.
