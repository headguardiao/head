# FORGE — Respostas para integração com o app principal (FinanceX)

Respondendo ponto a ponto o que foi perguntado sobre o backend FORGE
(`forge-heatmap`), pra quem estiver implementando a chamada a partir do
FinanceX (Node.js/Netlify/Supabase).

## 1. Onde está hospedado

**Só local, na máquina de desenvolvimento.** Não existe URL pública —
nunca foi publicado numa VPS/servidor. Roda em `http://localhost:8080`
via `python -m forge.app` (ou o atalho `run_dashboard.bat`).

Publicar isso numa URL acessível pelo Netlify ainda **não é seguro por
si só** — falta o item 5 (HTTPS). A autenticação (item 2) já está pronta.

## 2. Autenticação — implementado

**Atualização: já está implementado e testado.** Bearer token fixo,
exatamente como vocês sugeriram: todo endpoint (exceto `GET /health` e
`GET /signal/{symbol}`, dados públicos de mercado) exige o header
```
Authorization: Bearer <FORGE_API_KEY>
```
Sem o header, ou com valor errado, a resposta é `401
{"error": "missing or invalid Authorization header"}`.

A chave é uma string fixa, gerada uma vez, guardada como variável de
ambiente (`FORGE_API_KEY`) nos dois lados — **peça pra quem administra o
`forge-heatmap` te passar o valor por um canal seguro** (não por
histórico de chat) e guarde como env var secreta no Netlify. Coberto por
6 testes automatizados (chamada sem header, com header errado, com
header certo, header malformado, e confirmando que `/health`/`/signal`
continuam públicos mesmo com autenticação ligada) + verificação ao vivo
com `curl`.

## 3. `user_id` — pode ser o e-mail do aluno

Sim, funciona. O FORGE não valida formato nenhum — é uma string livre
usada só pra particionar os dados (`WHERE user_id = ?` no SQLite). Dois
pontos de atenção práticos, não bloqueantes:

- Ao usar em query string (`?user_id=`), o FinanceX precisa fazer
  URL-encode do e-mail (`@` e outros caracteres especiais) — `encodeURIComponent()` no Node resolve.
- O FORGE trata `user_id` como string exata, sem normalizar
  maiúsculas/minúsculas. Se o FinanceX já normaliza e-mail pra minúsculo
  antes de salvar no Supabase, mande sempre a mesma forma normalizada
  pro FORGE, senão `usuario@x.com` e `Usuario@x.com` viram dois
  "usuários" diferentes aqui.

## 4. Endpoints completos (conteúdo do `API.md`)

> Também existe como arquivo próprio (`API.md`, raiz do repositório
> `forge-heatmap`) — reproduzido aqui na íntegra pra não depender de
> acesso ao repositório.

---

# FORGE — Referência da API

Documento pra integrar seu app principal com este backend via HTTP. Não
tem SDK/cliente — são chamadas HTTP simples, JSON de ida e volta. Rodando
localmente, a base é `http://localhost:8080`.

**Autenticação por Bearer token obrigatória** (ver item 2 acima) — todo
endpoint exceto `GET /health` e `GET /signal/{symbol}`. `user_id` é um
identificador em texto livre passado em cada request *dentro* desse
espaço já autenticado — o servidor não valida se aquele `user_id`
"existe" de verdade, só particiona os dados por ele.

Erros seguem o padrão `{"error": "mensagem"}` com o status HTTP
apropriado (`400` parâmetro faltando/inválido, `401` credencial rejeitada
pela exchange, `404` não encontrado, `502` a exchange respondeu algo
inesperado/rate-limit).

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
Erros: `400` corpo inválido/campos faltando ou de tipo errado, `400`
exchange não suportada.

### `GET /accounts/connections?user_id=`
Lista as conexões do usuário (mesmo shape do item acima, em array).

### `DELETE /accounts/connections/{connection_id}?user_id=`
```json
{"status": "deleted"}
```
`404` se não existir pra esse `user_id`.

### `GET /accounts/connections/{connection_id}/balance?user_id=`
```json
{"exchange": "okx", "total_equity_usd": 1234.5, "available_usd": 1200.0, "raw": {}}
```
`404` conexão não encontrada, `401` credencial rejeitada pela exchange,
`502` erro/instabilidade da exchange.

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
Erros: `400` corpo inválido, campos faltando/tipo errado, `source`
desconhecido, ou `description` vazia quando `source` é `OWN`.

### `GET /strategies?user_id=`
Histórico completo (ativas e arquivadas), mais recente primeiro. Filtre
por `status == "ACTIVE"` no seu lado pra achar a vigente.

## Trading Ledger (`forge/ledger/`)

### `POST /accounts/connections/{connection_id}/sync-trades?user_id=`
Busca os fills/execuções recentes da exchange (janela recente, sem
paginação/histórico completo — ex: só últimos 3 dias na OKX) e grava
como `Trade`. Idempotente: repetir não duplica.
```json
{"new_trades": 4}
```
Erros: `404` conexão não encontrada, `401` credencial rejeitada, `502`
erro/instabilidade da exchange.

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

---

## 5. HTTPS

Ainda não existe URL pública, então HTTPS ainda não se aplica — mas
desde já: **este processo Python (aiohttp) não termina TLS sozinho**.
Quando formos publicar, vai precisar ficar atrás de um proxy reverso
(nginx, Caddy, ou o load balancer da própria VPS/plataforma de deploy)
com certificado válido (Let's Encrypt, por exemplo) — o FORGE em si só
fala HTTP puro na porta 8080. Isso é trabalho de infraestrutura, não de
código do FORGE.

## 6. Formato de erro — confirmado, com uma ressalva importante

**Sim, confirmado: todo erro vem como `{"error": "mensagem"}` com o
status HTTP correto — 400/401/404/502, sem exceção.**

Ressalva por transparência: ao verificar essa garantia com rigor (não
só ler o código, escrevi testes de verdade batendo na API), encontrei e
corrigi **dois bugs reais** nos endpoints `POST /accounts/connections` e
`POST /strategies` — se o corpo da requisição não fosse um JSON válido
(ex: corpo vazio, JSON malformado, ou um array em vez de objeto), o
servidor caía num erro genérico do aiohttp em texto puro, não em JSON.
Já corrigido, testado (8 testes novos batendo direto na API simulando
corpo malformado) e confirmado ao vivo com `curl`. Então a resposta é
sim, mas é sim **a partir de agora**, não era 100% verdade antes desta
conversa.

## Pendências antes de publicar numa URL acessível pelo Netlify

1. ~~Implementar autenticação Bearer token~~ — feito (item 2).
2. Decidir onde hospedar (VPS própria? Alguma plataforma?) e configurar
   HTTPS na frente (item 5) — ainda não decidido/feito.
3. Depois disso, sim, faz sentido publicar a URL e integrar de verdade.
