import { pathToFileURL } from 'node:url';
import { createServer } from './api/server.js';
import { env } from './config/env.js';
import { logger } from './config/logger.js';
import { BinanceAdapter } from './exchanges/binance/BinanceAdapter.js';
import { OKXAdapter } from './exchanges/okx/OKXAdapter.js';
import { BybitAdapter } from './exchanges/bybit/BybitAdapter.js';
import { BitgetAdapter } from './exchanges/bitget/BitgetAdapter.js';
import { MarketState } from './engine/marketState.js';
import { symbolsFor } from './normalizer/symbols.js';

export async function main() {
  const marketStates = new Map(env.symbols.map((s) => [s, new MarketState(s)]));

  // Public data only: order book, trades, open interest, funding, and
  // liquidations where the exchange makes them straightforward to stream
  // (Binance forceOrder, Bybit allLiquidation, OKX liquidation-orders;
  // Bitget's liquidation channel isn't wired up yet). Any other exchange
  // gets wired up the same way: a new ExchangeAdapter subclass under
  // src/exchanges/<name>/, pushed onto this array. Each adapter only gets
  // the symbols it actually has an instrument mapping for - not every
  // tracked symbol has a live perpetual on all four exchanges (e.g.
  // BONK/PEPE are missing from Binance/Bybit here).
  const adapters = [
    new BinanceAdapter({ symbols: symbolsFor('binance', env.symbols) }),
    new OKXAdapter({ symbols: symbolsFor('okx', env.symbols) }),
    new BybitAdapter({ symbols: symbolsFor('bybit', env.symbols) }),
    new BitgetAdapter({ symbols: symbolsFor('bitget', env.symbols) }),
  ];

  for (const adapter of adapters) {
    adapter.on('orderbook', (event) => {
      marketStates.get(event.symbol)?.onOrderbook(event);
    });
    adapter.on('trade', (event) => {
      marketStates.get(event.symbol)?.onTrade(event);
    });
    adapter.on('openInterest', (event) => {
      marketStates.get(event.symbol)?.onOpenInterest(event);
    });
    adapter.on('funding', (event) => {
      marketStates.get(event.symbol)?.onFunding(event);
    });
    adapter.on('liquidation', (event) => {
      marketStates.get(event.symbol)?.onLiquidation(event);
    });
    adapter.on('error', (err) => {
      logger.error(`[${adapter.name}] ${err.stack || err.message}`);
    });
  }

  const startedAt = Date.now();
  const app = createServer({ marketStates, adapters, startedAt });

  const port = env.port;
  const server = app.listen(port, '0.0.0.0', () => {
    logger.info(`HTTP API listening on http://0.0.0.0:${port}`);
  });

  for (const adapter of adapters) {
    adapter.start();
  }

  let shuttingDown = false;
  async function shutdown(signal) {
    if (shuttingDown) return;
    shuttingDown = true;
    logger.info(`received ${signal}, shutting down gracefully`);
    server.close();
    await Promise.all(adapters.map((a) => a.stop()));
    process.exit(0);
  }

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));

  return { app, server, adapters, marketStates };
}

// pathToFileURL normalizes Windows backslashes/drive letters to match
// import.meta.url's file:// format - a plain `file://${argv[1]}` string
// comparison silently never matches on Windows, so main() would never run.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((err) => {
    logger.error(`fatal startup error: ${err.stack || err.message}`);
    process.exit(1);
  });
}
