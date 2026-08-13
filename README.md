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

## Segurança

Todo o pipeline usa **apenas dados públicos de mercado** — nenhuma API key
é necessária para order book, trades, OI, funding ou liquidações. Não há
nenhuma chave de exchange neste repositório. Quando (e se) módulos de
execução forem adicionados, as chaves privadas devem ficar em um secret
manager separado deste módulo de análise, nunca no código.

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
