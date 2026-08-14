import express from 'express';
import { logger } from '../config/logger.js';

export function createServer({ marketStates, adapters, startedAt }) {
  const app = express();

  // Read-only public market data, no auth/cookies involved - safe to allow
  // any origin so a browser-based dashboard can poll this API directly.
  app.use((_req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET');
    next();
  });

  app.get('/health', (_req, res) => {
    const exchanges = {};
    for (const adapter of adapters) {
      exchanges[adapter.name] = {
        connected: adapter.connected,
        lastMessageAgeMs: adapter.lastMessageAt ? Date.now() - adapter.lastMessageAt : null,
      };
    }
    res.json({
      status: 'ok',
      uptimeSec: Math.round((Date.now() - startedAt) / 1000),
      exchanges,
    });
  });

  app.get('/api/market/:symbol', (req, res) => {
    const symbol = req.params.symbol.toUpperCase();
    const state = marketStates.get(symbol);
    if (!state) {
      res.status(404).json({ error: `unknown symbol ${symbol}` });
      return;
    }
    res.json(state.snapshot());
  });

  app.get('/api/score/:symbol', (req, res) => {
    const symbol = req.params.symbol.toUpperCase();
    const state = marketStates.get(symbol);
    if (!state) {
      res.status(404).json({ error: `unknown symbol ${symbol}` });
      return;
    }
    res.json({ symbol, ...state.score() });
  });

  app.use((_req, res) => {
    res.status(404).json({ error: 'not found' });
  });

  // Express requires a 4-arg signature to recognize this as an error handler.
  // eslint-disable-next-line no-unused-vars
  app.use((err, _req, res, _next) => {
    logger.error(`unhandled API error: ${err.stack || err.message}`);
    res.status(500).json({ error: 'internal error' });
  });

  return app;
}
