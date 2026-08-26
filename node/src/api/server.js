import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import { logger } from '../config/logger.js';
import { env } from '../config/env.js';
import { computeGlassnodeSentiment, emptyGlassnodePayload } from '../engine/glassnodeSentiment.js';

const publicDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');

function summarizeDiagnostics(diagnostics) {
  const symbols = Object.values(diagnostics.symbols);
  return {
    synced: symbols.filter((d) => d.synced).length,
    total: symbols.length,
    lastError: diagnostics.lastError,
    bannedUntil: diagnostics.bannedUntil,
  };
}

export function createServer({ marketStates, adapters, startedAt }) {
  const app = express();

  // Read-only public market data, no auth/cookies involved - safe to allow
  // any origin so a browser-based dashboard can poll this API directly.
  app.use((_req, res, next) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET');
    next();
  });

  app.get('/dashboard', (_req, res) => {
    res.sendFile(path.join(publicDir, 'dashboard.html'));
  });

  app.get('/health', (_req, res) => {
    const exchanges = {};
    for (const adapter of adapters) {
      exchanges[adapter.name] = {
        connected: adapter.connected,
        lastMessageAgeMs: adapter.lastMessageAt ? Date.now() - adapter.lastMessageAt : null,
        // Binance needs a REST snapshot per symbol before it contributes
        // to the aggregated book - "connected" alone doesn't mean synced.
        ...(adapter.diagnostics ? { syncedSymbols: summarizeDiagnostics(adapter.diagnostics()) } : {}),
      };
    }
    res.json({
      status: 'ok',
      uptimeSec: Math.round((Date.now() - startedAt) / 1000),
      exchanges,
    });
  });

  app.get('/api/symbols', (_req, res) => {
    res.json({ symbols: env.symbols });
  });

  app.get('/api/diagnostics/binance', (_req, res) => {
    const adapter = adapters.find((a) => a.name === 'binance');
    if (!adapter?.diagnostics) {
      res.status(404).json({ error: 'binance adapter not available' });
      return;
    }
    res.json(adapter.diagnostics());
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

  app.get('/api/score/:symbol', async (req, res) => {
    const symbol = req.params.symbol.toUpperCase();
    const state = marketStates.get(symbol);
    if (!state) {
      res.status(404).json({ error: `unknown symbol ${symbol}` });
      return;
    }
    const score = state.score();
    const signalFields = score.hasEnoughData
      ? { signalReady: score.confidence >= env.signalMinConfidence, minConfidenceRequired: env.signalMinConfidence }
      : {};

    let glassnode;
    try {
      glassnode = await computeGlassnodeSentiment(symbol);
    } catch (err) {
      // computeGlassnodeSentiment is designed to never throw; this is a
      // last-resort guard so a Glassnode outage can never take /api/score down.
      logger.error(`glassnode sentiment failed unexpectedly: ${err.stack || err.message}`);
      glassnode = emptyGlassnodePayload(false, ['glassnode internal error']);
    }

    res.json({ symbol, ...score, ...signalFields, glassnode });
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
