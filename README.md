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
  aderência de verdade (blueprint seção 20) não existe nesta versão. Motor
  de insight comportamental, jobs agendados e o chat de perguntas
  sugestivas (`FORGE Modulo Comportamental e Estrategia Spec.pdf`) ficam
  para uma próxima rodada — dependem de dados reais fluindo por aqui
  primeiro.

## Segurança

Todo o pipeline de mercado usa **apenas dados públicos** — nenhuma API key
é necessária para order book, trades, OI, funding ou liquidações.

`forge/accounts/` (conexões privadas) é diferente: guarda API key/secret
do usuário cifrados com `Fernet` (chave em `FORGE_ENCRYPTION_KEY`, nunca
no repositório — veja `.env.example`). Nenhuma chave/secret é devolvida
por qualquer endpoint. **Este módulo ainda não tem autenticação real**
— os endpoints `/accounts/*` identificam o "usuário" por um `user_id` de
texto livre no request, sem verificação nenhuma (a etapa "01 Foundation"
do blueprint, que cobre login/auth de verdade, foi propositalmente
pulada). Isso é aceitável só para desenvolvimento local; **não exponha a
porta 8080 publicamente enquanto isso não mudar** — a mesma recomendação
de firewall abaixo vale em dobro aqui, já que agora há segredos reais em
jogo, não só dados públicos de mercado.

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
