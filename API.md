# FORGE — Referência da API

Documento pra integrar seu app principal com este backend via HTTP. Não
tem SDK/cliente — são chamadas HTTP simples, JSON de ida e volta. Rodando
localmente, a base é `http://localhost:8080`.

**Autenticação por Bearer token**, se o servidor foi iniciado com
`FORGE_API_KEY` definida (ver `.env.example`) — obrigatória em todo
endpoint, exceto `GET /health` e `GET /signal/{symbol}` (dados públicos
de mercado, sem `user_id`):
```
Authorization: Bearer <FORGE_API_KEY>
```
Sem o header (ou com valor errado), a resposta é `401
{"error": "missing or invalid Authorization header"}`. Se o servidor foi
iniciado **sem** `FORGE_API_KEY`, não há autenticação nenhuma — aceitável
só para uso local, nunca com a porta alcançável de fora.

`user_id` continua sendo um identificador em texto livre dentro do
espaço autenticado — o Bearer token autentica a *chamada* (é você, app
principal), o `user_id` só particiona os dados entre usuários finais; o
servidor não valida se aquele `user_id` "existe" de verdade.

Erros seguem o padrão `{"error": "mensagem"}` com o status HTTP
apropriado (`400` parâmetro faltando/inválido, `401` credencial rejeitada
pela exchange, `404` não encontrado, `502` a exchange respondeu algo
inesperado/rate-limit).

---

## Dados públicos de mercado (sem user_id, sem chave)

### `GET /signal/{symbol}`
Heatmap de liquidez agregado + `LIQUIDITY_SCORE`. `symbol` ex: `BTCUSDT`.
Retorna `404` (`{"error": "unknown symbol ..."}`) para símbolos fora de
`config/settings.py:SYMBOLS`.
```json
{
  "symbol": "BTCUSDT",
  "liquidity_score": 78.4,
  "bias": "long",
  "concentration_above_usd": 1200000.0,
  "concentration_below_usd": 800000.0,
  "orderbook_imbalance": 0.12,
  "oi_change_pct": 1.5,
  "funding_rate": 0.0001,
  "liquidation_notional_usd": 50000.0,
  "top_liquidity_walls": [{"price": 61200.0, "bid_notional_usd": 50000.0, "ask_notional_usd": 300000.0}],
  "confidence": 1.0,
  "connected_exchanges": 4
}
```

### `GET /health`
```json
{"status": "ok"}
```

---

## Conexões de exchange (`forge/accounts/`)

Cada conexão guarda uma API key/secret de exchange cifrada, vinculada a
um `user_id`. Todos os endpoints abaixo fazem chamadas reais e
autenticadas pra exchange (não são cacheados).

### `POST /accounts/connections`
Cria e valida uma conexão (a validação é uma chamada real de saldo — a
exchange rejeitando credenciais erradas é o que define `status`).

Body:
```json
{
  "user_id": "string, obrigatório",
  "exchange": "binance | bybit | bitget | okx, obrigatório",
  "api_key": "string, obrigatório",
  "api_secret": "string, obrigatório",
  "passphrase": "string, obrigatório só para bitget/okx",
  "label": "string, opcional"
}
```
Resposta (`201`):
```json
{
  "connection_id": "uuid",
  "user_id": "string",
  "exchange": "okx",
  "account_identifier": "okx-user123",
  "permissions": "READ_ONLY",
  "status": "ACTIVE | INVALID",
  "last_sync": 1786700000.0,
  "created_at": 1786700000.0,
  "updated_at": 1786700000.0
}
```
`api_key`/`api_secret`/`passphrase` nunca voltam em nenhuma resposta.

### `GET /accounts/connections?user_id=`
Lista as conexões do usuário (mesmo shape do item acima, em array).

### `DELETE /accounts/connections/{connection_id}?user_id=`
```json
{"status": "deleted"}
```

### `GET /accounts/connections/{connection_id}/balance?user_id=`
```json
{"exchange": "okx", "total_equity_usd": 1234.5, "available_usd": 1200.0, "raw": {}}
```

### `GET /accounts/connections/{connection_id}/positions?user_id=`
Array de:
```json
{
  "exchange": "okx", "symbol": "BTCUSDT", "side": "LONG", "size": 0.05,
  "entry_price": 61000.0, "unrealized_pnl": 12.3, "leverage": 10.0
}
```

### `GET /accounts/connections/{connection_id}/orders?user_id=`
Array de:
```json
{
  "exchange": "okx", "order_id": "123", "symbol": "BTCUSDT", "side": "BUY",
  "price": 60000.0, "qty": 0.01, "status": "live"
}
```

---

## Estratégia (`forge/strategies/`)

Só uma estratégia fica `ACTIVE` por usuário — criar/ativar uma nova
arquiva a anterior automaticamente.

### `GET /strategies/templates`
Templates FinanceX disponíveis pra ativação direta (sem escrever nada):
```json
[
  {"source": "FINANCEX_NORMAL", "name": "FinanceX Normal", "description": "SMA21 + SMA8 + Pivot Point SuperTrend + volume"},
  {"source": "FINANCEX_ELITE", "name": "FinanceX Elite", "description": "Pullback + volume"}
]
```

### `POST /strategies`
Body pra estratégia própria:
```json
{"user_id": "string", "source": "OWN", "name": "opcional", "description": "obrigatório"}
```
Body pra template FinanceX:
```json
{"user_id": "string", "source": "FINANCEX_NORMAL"}
```
Resposta (`201`):
```json
{
  "strategy_id": "uuid", "user_id": "string", "source": "OWN",
  "name": "Minha estratégia", "description": "...", "status": "ACTIVE",
  "created_at": 1786700000.0, "activated_at": 1786700000.0
}
```

### `GET /strategies?user_id=`
Histórico completo (ativas e arquivadas), mais recente primeiro. Filtre
por `status == "ACTIVE"` no seu lado pra achar a vigente.

---

## Trading Ledger (`forge/ledger/`)

### `POST /accounts/connections/{connection_id}/sync-trades?user_id=`
Busca os fills/execuções recentes da exchange (janela recente, sem
paginação/histórico completo — ex: só últimos 3 dias na OKX) e grava
como `Trade`. Idempotente: repetir não duplica.
```json
{"new_trades": 4}
```

### `GET /trades?user_id=`
Array de:
```json
{
  "trade_id": "uuid", "user_id": "string", "exchange": "okx",
  "external_id": "id-na-exchange", "symbol": "BTCUSDT",
  "market_type": "PERPETUAL_FUTURES", "side": "BUY", "quantity": 0.01,
  "price": 61000.0, "fee": 0.05, "gross_pnl": 12.3, "net_pnl": 12.25,
  "funding": null, "slippage": null, "order_id": "...",
  "opened_at": 1786700000.0, "source": "okx",
  "verification_status": "VERIFIED"
}
```
`gross_pnl`/`net_pnl` são `null` quando a exchange não reporta PnL
realizado por fill (caso da OKX hoje). `funding`/`slippage` são sempre
`null` nesta versão — não computados ainda.

---

## Análise Comportamental (`forge/insights/`)

Sob demanda (sem job automático). Precisa de no mínimo 15 trades numa
categoria pra gerar um insight de verdade — abaixo disso, devolve
explicitamente um insight de categoria `insufficient_data` em vez de
inventar um padrão.

### `POST /insights/generate?user_id=`
Calcula agora a partir dos trades já sincronizados e persiste o
resultado. Array de:
```json
{
  "insight_id": "uuid", "user_id": "string",
  "category": "performance_por_estrategia | consistencia_horario | insufficient_data",
  "text": "Operando estratégia FINANCEX_ELITE, sua taxa de acerto é 67% em 15 trades, com PnL líquido médio de 5.3333.",
  "evidence": {"origin": "FINANCEX_ELITE", "win_rate": 0.667, "avg_net_pnl": 5.33, "sample_size": 15},
  "sample_size": 15,
  "generated_at": 1786700000.0
}
```
`evidence` varia por categoria — ver `forge/insights/engine.py` pros
campos exatos de cada uma.

### `GET /insights?user_id=`
Histórico de todas as análises já geradas, mais recente primeiro.
