# FORGE — Integração com o App Principal

Documento de handoff para quem for implementar, no app principal, o
consumo dos dados do backend FORGE (repositório `forge-heatmap`). Não é
a referência técnica dos endpoints — isso está em `API.md`, no mesmo
repositório, e este documento assume que você vai ler aquele em
seguida. Aqui está o contexto de como as duas partes se encaixam, o
fluxo recomendado, e os pontos que geram bug/confusão se ignorados.

## 1. O que é o FORGE, nesta fase

Um backend Python (aiohttp) que:
- Lê dados públicos de mercado (order book, liquidez agregada) de
  Binance/OKX/Bybit/Bitget — não depende de nenhum usuário.
- Guarda conexões privadas por usuário (API key/secret de exchange,
  cifradas em repouso) e expõe saldo, posições, ordens abertas e
  histórico recente de trades dessas contas.
- Deixa o usuário escolher uma estratégia (a própria, em texto livre, ou
  um template FinanceX Normal/Elite) — só uma fica ativa por vez.
- Calcula, sob demanda, insights comportamentais simples (performance
  por estratégia, consistência por horário) a partir dos trades
  sincronizados.

Roda como um processo HTTP simples, sem banco de dados externo (SQLite
local) e sem fila/mensageria. `python -m forge.app` sobe tudo numa porta
só (padrão `8080`).

## 2. Onde ele roda e como o app principal alcança

Hoje roda **local**, na máquina de desenvolvimento (via
`run_dashboard.bat` ou `python -m forge.app` direto). Se o app principal
roda:
- **Na mesma máquina**: chame `http://localhost:8080`.
- **Em outra máquina/rede que você controla, ou de fora (ex: Netlify
  Functions)**: chame pelo IP/hostname público — mas só depois de
  `FORGE_API_KEY` estar configurada (seção 4) e o endereço ter HTTPS de
  verdade na frente (seção 5, ainda pendente hoje).

Todas as chamadas descritas aqui assumem **servidor-a-servidor**
(backend do app principal chamando o FORGE) — não CORS, não é pra
chamar direto do navegador do usuário final.

## 3. O conceito-chave: `user_id`

O FORGE não tem sistema de contas/login próprio. Todo endpoint que lida
com dados de um usuário recebe um `user_id` em texto livre — o FORGE
simplesmente particiona os dados por essa string, sem validar quem é.

**Decisão que o app principal precisa tomar**: usar o mesmo ID de usuário
que já existe no seu sistema de autenticação como o `user_id` passado ao
FORGE (ex: o `user.id` do seu banco). Assim os dados batem 1:1 sem
precisar de uma tabela de mapeamento. Isso também significa que **é
responsabilidade do app principal garantir que um usuário só veja os
dados do próprio `user_id`** — o FORGE não impõe isso.

## 4. Segurança — o que o app principal precisa saber

- **Autenticação por Bearer token, já implementada.** Todo endpoint
  (exceto `GET /health` e `GET /signal/{symbol}`, dados públicos de
  mercado) exige o header `Authorization: Bearer <FORGE_API_KEY>`. Sem
  isso, ou com o valor errado, a resposta é `401`. A chave é uma string
  fixa gerada uma vez e guardada nos `.env` dos dois lados — **peça a
  quem administra o FORGE pra te passar o valor de `FORGE_API_KEY` por
  um canal seguro** (não por chat), e guarde como variável de ambiente
  secreta no Netlify (nunca no código-fonte do FinanceX).
- Esse token autentica a *chamada* (confirma que é o backend do app
  principal falando), não o usuário final — o `user_id` continua sendo
  texto livre dentro do espaço já autenticado. Qualquer processo que
  tiver o token pode ler/escrever dados de **qualquer** `user_id`, então
  o token em si precisa ficar só no backend do FinanceX, nunca no
  frontend/navegador do usuário final.
- As API keys de exchange do usuário devem ir **do backend do app
  principal direto pro FORGE** (`POST /accounts/connections`) — nunca
  devem passar pelo frontend/navegador do app principal em texto puro
  além do necessário, e nunca devem ser logadas.
- O FORGE cifra a key/secret em repouso e nunca devolve esses valores em
  nenhuma resposta (nem mascarados) — se o app principal precisar
  "lembrar" que tipo de exchange/rótulo foi conectado, guarde isso do
  seu próprio lado ou consulte `GET /accounts/connections?user_id=`
  (que devolve status/rótulo, nunca a credencial).

## 5. Fluxo recomendado

1. **Usuário conecta uma exchange** no app principal → o backend do app
   principal repassa pro FORGE:
   `POST /accounts/connections` com `user_id`, `exchange`, `api_key`,
   `api_secret` (e `passphrase` se for Bitget/OKX). A resposta traz
   `status: "ACTIVE"` ou `"INVALID"` — trate isso na hora (mostre erro
   claro pro usuário se vier `INVALID`, não deixe silencioso).
2. **Mostrar saldo/posições/ordens ao vivo**: `GET
   .../balance|positions|orders` — são chamadas reais na exchange a cada
   request, não cacheadas. Não chame em loop apertado; puxe sob demanda
   (usuário abriu a tela) ou num intervalo razoável (ex: a cada alguns
   minutos), nunca por segundo.
3. **Sincronizar histórico de trades**: `POST
   .../sync-trades?user_id=` periodicamente (o FORGE não tem agendador
   próprio — se você quer isso automático, o cron precisa estar do lado
   do app principal, chamando esse endpoint). É idempotente (pode
   chamar de novo sem duplicar). Cada exchange só devolve uma janela
   recente (ex: 3 dias na OKX) — não é histórico completo.
4. **Usuário escolhe estratégia**: `GET /strategies/templates` pra
   listar as opções prontas, `POST /strategies` pra criar/ativar (própria
   ou template). Sempre confira `GET /strategies?user_id=` filtrando
   `status == "ACTIVE"` pra saber a vigente.
5. **Gerar análise comportamental**: `POST
   /insights/generate?user_id=` sob demanda (ex: usuário clicou "ver
   minha análise", ou um cron periódico do app principal). Com poucos
   trades sincronizados (< 15 numa categoria), a resposta vem com
   `category: "insufficient_data"` — **isso não é erro**, é o FORGE
   dizendo honestamente que ainda não tem base pra opinar. Trate esse
   caso na UI (ex: "sincronize mais operações pra desbloquear sua
   análise"), não como falha.

## 6. Tratamento de erros

Todo erro vem como `{"error": "mensagem"}` com o status HTTP:
- `400`: parâmetro faltando/inválido — bug de integração do seu lado,
  corrija a chamada.
- `401`: a exchange rejeitou a credencial (chave errada, IP não
  liberado, permissão insuficiente) — mostre isso pro usuário, ele
  precisa corrigir a conexão.
- `404`: `connection_id` não existe pra aquele `user_id`.
- `502`: a exchange respondeu algo inesperado (rate limit, instabilidade
  momentânea) — não é culpa do usuário nem do app principal; vale tentar
  de novo mais tarde, não é permanente.

## 7. Limitações atuais (não tentar contornar, são intencionais)

- Sem histórico completo de trades, só janela recente por sincronização.
- Sem cálculo de `funding`/`slippage` por trade (sempre `null`).
- Sem Adherence Engine de verdade — trades linkados a uma estratégia
  ficam com `classification: "UNKNOWN"`, não `PASS`/`FAIL`.
- Sem chat/IA nos insights — texto gerado por template, não por modelo.
- Uma estratégia ativa por usuário por vez, não múltiplas simultâneas.

## 8. Referência completa dos endpoints

Ver `API.md` neste mesmo repositório — todos os endpoints, shapes de
request/resposta e exemplos, verificados contra o código real.
