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
