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
é necessária para order book, trades, OI, funding ou liquidações.

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
