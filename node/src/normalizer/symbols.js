// Canonical symbol -> per-exchange instrument id. Extend this table when
// adding symbols or more exchanges.
const SYMBOL_MAP = {
  BTCUSDT: { binance: 'BTCUSDT', okx: 'BTC-USDT-SWAP' },
  ETHUSDT: { binance: 'ETHUSDT', okx: 'ETH-USDT-SWAP' },
};

const REVERSE = new Map();
for (const [canonical, byExchange] of Object.entries(SYMBOL_MAP)) {
  for (const [exchange, exSymbol] of Object.entries(byExchange)) {
    REVERSE.set(`${exchange}:${exSymbol}`, canonical);
  }
}

export function exchangeSymbol(canonical, exchange) {
  const entry = SYMBOL_MAP[canonical];
  if (!entry || !entry[exchange]) {
    throw new Error(`No symbol mapping for ${canonical} on ${exchange}`);
  }
  return entry[exchange];
}

export function canonicalFromExchange(exchange, exchangeSymbolValue) {
  return REVERSE.get(`${exchange}:${exchangeSymbolValue}`) ?? null;
}

export function trackedSymbols() {
  return Object.keys(SYMBOL_MAP);
}
