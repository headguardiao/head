# Forge Heatmap Multiexchange — Node.js (fase de teste)

Implementação Node.js do Forge, isolada do protótipo Python que vive em
`../` (fora desta pasta) — nenhum dos dois mexe no código do outro.

**Escopo desta fase:** **Binance, OKX, Bybit e Bitget** (94 símbolos —
veja `src/normalizer/symbols.js`), dados públicos de mercado (order book +
trades), sem API keys privadas, sem execução de ordens. Open interest,
funding e liquidações ficam para uma fase seguinte — a arquitetura já foi
deixada pronta para isso (veja "Como adicionar uma exchange" abaixo).

```
Exchange WS/REST → Adapter → Normalizer (schema validado com zod) →
  Liquidity Engine → Score Engine (provisório) → API HTTP
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

Nenhuma API key é lida de env var — o pipeline inteiro usa apenas
endpoints públicos.

## Endpoints

- `GET /health` — status do processo (uptime) + estado de conexão de cada
  exchange (`connected`, `lastMessageAgeMs`).
- `GET /api/market/:symbol` — estado normalizado atual: mid price,
  exchanges conectadas, imbalance do order book, maiores paredes de
  liquidez, contagem de trades recentes.
- `GET /api/score/:symbol` — `{ hasEnoughData: false, reason }` se ainda
  não há order book para o símbolo, ou o score provisório com
  `liquidityScore`, `bias`, `confidence` e o detalhamento por componente.

**O score desta fase é provisório**, calculado só com o que é coletado
agora (concentração de liquidez, imbalance do order book, fluxo de
trades recente, confirmação entre Binance+OKX). Ele **não** é o
`LIQUIDITY_SCORE` completo da arquitetura original — falta open interest,
funding e liquidações, que exigem os adapters dessas exchanges/streams
ainda não implementados nesta fase.

## Como adicionar uma exchange

1. Criar `src/exchanges/<nome>/<Nome>Adapter.js` estendendo
   `ExchangeAdapter` (`src/exchanges/base/ExchangeAdapter.js`) e
   implementando `getWsUrl()`, `getSubscribeMessages()` (se aplicável) e
   `handleMessage(raw)`.
2. Adicionar o mapeamento de símbolo em `src/normalizer/symbols.js`.
3. Emitir eventos `orderbook`/`trade` já validados pelo schema
   (`src/normalizer/validate.js`).
4. Registrar a nova instância em `src/index.js` (array `adapters`).

## Limitações conhecidas

- Sem open interest, funding rate ou liquidações ainda — o score é
  parcial (ver acima).
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
