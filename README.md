# Forge — Heatmap Multiexchange

Módulo independente de inteligência de mercado: agrega order book, trades,
open interest, funding e liquidações da Binance, OKX, Bybit e Bitget
(Fase 1), normaliza tudo em notional USD (Fase 2), calcula um heatmap de
liquidez agregado (Fase 2) e um `LIQUIDITY_SCORE` de 0–100 (Fases 3–4),
seguindo `Forge_Heatmap_Multiexchange_Architecture.pdf`.

Fases 5 (Gate.io, KuCoin, MEXC, BingX, BitMart, HTX, CoinEx) e 6
(backtest/validação antes de permitir que o score altere entradas/saídas
automaticamente) ainda não estão implementadas.

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

## Segurança

Todo o pipeline de mercado usa **apenas dados públicos** — nenhuma API key
é necessária para order book, trades, OI, funding ou liquidações. Não há
nenhuma chave de exchange neste repositório. Quando (e se) módulos de
execução forem adicionados, as chaves privadas devem ficar em um secret
manager separado deste módulo de análise, nunca no código.

A única exceção é `GLASSNODE_API_KEY` (env var, opcional), usada só pelo
bloco de sentimento on-chain descrito abaixo — sem ela o resto do serviço
continua 100% funcional, só o bloco `glassnode` vem com `has_key: false`.

## Rodar localmente

Requer Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m forge.app
```

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
variação 24h da reserva em exchange, supply de stablecoins), cada um
normalizado -100..+100, agregados em `glassnode_score` /
`glassnode_bias` (`RISK_ON`/`RISK_OFF`/`NEUTRAL`) / `glassnode_confidence`.
Símbolos que não sejam BTCUSDT/ETHUSDT ancoram na camada BTC
(`asset_used: "BTC"`, `asset_direct: false`) em vez de escanear o
catálogo Glassnode em runtime. Sem chave, ou com chave inválida,
`has_key` vem `false` e todos os componentes vêm `avail: false` — o
endpoint continua respondendo 200 normalmente, nada mais no payload é
afetado. O serviço Node (`node/`) expõe o mesmo bloco, no mesmo formato,
em `GET /api/score/:symbol` — ver `node/README.md`.

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
(`ufw allow from <seu-ip> to any port 8080`) — a API não tem autenticação.

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
