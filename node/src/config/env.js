import { trackedSymbols } from '../normalizer/symbols.js';

function parseSymbols(raw) {
  if (!raw) return trackedSymbols();
  return raw
    .split(',')
    .map((s) => s.trim().toUpperCase())
    .filter(Boolean);
}

// Only non-sensitive configuration belongs here (symbols, region, tuning
// knobs). No API keys, secrets, or credentials are read from env vars.
export const env = {
  port: Number(process.env.PORT) || 3000,
  symbols: parseSymbols(process.env.SYMBOLS),
  region: process.env.REGION || 'default',
  orderBookDepth: Number(process.env.ORDER_BOOK_DEPTH) || 50,
  maxTradesPerSymbol: Number(process.env.MAX_TRADES_PER_SYMBOL) || 2000,
  logLevel: process.env.LOG_LEVEL || 'info',
  // Minimum `confidence` for /api/score to report signalReady=true.
  // Mirrors config/settings.py SIGNAL_MIN_CONFIDENCE.
  signalMinConfidence: Number(process.env.SIGNAL_MIN_CONFIDENCE) || 60,
};
