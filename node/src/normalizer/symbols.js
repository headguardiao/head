// Canonical symbol -> per-exchange instrument id (+ OKX's contract value,
// see below). Canonical keys follow Binance's own BASEUSDT ticker format
// (the scheme this codebase's API routes/tests already use), not the bare
// base asset. Extend this table when adding symbols or more exchanges.
//
// Generated from live Binance USDS-M futures exchangeInfo and OKX SWAP
// instruments (2026-08-13): every symbol below has a TRADING/live USDT
// perpetual on at least one of the two exchanges. Dropped from the
// requested list because neither exchange has a live perpetual for them:
// LRC, NKN, SXP, TON (Binance lists TON/LRC/NKN but flagged SETTLING -
// being delisted - so they're excluded here too).
const SYMBOL_MAP = {
  '1INCHUSDT': { binance: '1INCHUSDT', okx: '1INCH-USDT-SWAP', okxCtVal: 1 },
  ADAUSDT: { binance: 'ADAUSDT', okx: 'ADA-USDT-SWAP', okxCtVal: 100 },
  ALGOUSDT: { binance: 'ALGOUSDT', okx: 'ALGO-USDT-SWAP', okxCtVal: 10 },
  ALICEUSDT: { binance: 'ALICEUSDT' },
  ANKRUSDT: { binance: 'ANKRUSDT' },
  APEUSDT: { binance: 'APEUSDT', okx: 'APE-USDT-SWAP', okxCtVal: 0.1 },
  APTUSDT: { binance: 'APTUSDT', okx: 'APT-USDT-SWAP', okxCtVal: 1 },
  ARBUSDT: { binance: 'ARBUSDT', okx: 'ARB-USDT-SWAP', okxCtVal: 10 },
  ARPAUSDT: { binance: 'ARPAUSDT' },
  ARUSDT: { binance: 'ARUSDT', okx: 'AR-USDT-SWAP', okxCtVal: 0.1 },
  ATOMUSDT: { binance: 'ATOMUSDT', okx: 'ATOM-USDT-SWAP', okxCtVal: 1 },
  AVAXUSDT: { binance: 'AVAXUSDT', okx: 'AVAX-USDT-SWAP', okxCtVal: 1 },
  AXSUSDT: { binance: 'AXSUSDT', okx: 'AXS-USDT-SWAP', okxCtVal: 0.1 },
  BANDUSDT: { binance: 'BANDUSDT', okx: 'BAND-USDT-SWAP', okxCtVal: 1 },
  BATUSDT: { binance: 'BATUSDT', okx: 'BAT-USDT-SWAP', okxCtVal: 10 },
  BCHUSDT: { binance: 'BCHUSDT', okx: 'BCH-USDT-SWAP', okxCtVal: 0.1 },
  BELUSDT: { binance: 'BELUSDT' },
  BNBUSDT: { binance: 'BNBUSDT', okx: 'BNB-USDT-SWAP', okxCtVal: 0.01 },
  BONKUSDT: { okx: 'BONK-USDT-SWAP', okxCtVal: 100000 },
  BTCUSDT: { binance: 'BTCUSDT', okx: 'BTC-USDT-SWAP', okxCtVal: 0.01 },
  CELOUSDT: { binance: 'CELOUSDT', okx: 'CELO-USDT-SWAP', okxCtVal: 1 },
  CHZUSDT: { binance: 'CHZUSDT', okx: 'CHZ-USDT-SWAP', okxCtVal: 10 },
  COMPUSDT: { binance: 'COMPUSDT', okx: 'COMP-USDT-SWAP', okxCtVal: 0.1 },
  COTIUSDT: { binance: 'COTIUSDT' },
  CYBERUSDT: { binance: 'CYBERUSDT' },
  DASHUSDT: { binance: 'DASHUSDT', okx: 'DASH-USDT-SWAP', okxCtVal: 0.01 },
  DOGEUSDT: { binance: 'DOGEUSDT', okx: 'DOGE-USDT-SWAP', okxCtVal: 1000 },
  DOTUSDT: { binance: 'DOTUSDT', okx: 'DOT-USDT-SWAP', okxCtVal: 1 },
  DUSKUSDT: { binance: 'DUSKUSDT' },
  DYDXUSDT: { binance: 'DYDXUSDT', okx: 'DYDX-USDT-SWAP', okxCtVal: 1 },
  EGLDUSDT: { binance: 'EGLDUSDT', okx: 'EGLD-USDT-SWAP', okxCtVal: 0.1 },
  ENAUSDT: { binance: 'ENAUSDT', okx: 'ENA-USDT-SWAP', okxCtVal: 10 },
  ENJUSDT: { binance: 'ENJUSDT', okx: 'ENJ-USDT-SWAP', okxCtVal: 10 },
  ENSUSDT: { binance: 'ENSUSDT', okx: 'ENS-USDT-SWAP', okxCtVal: 0.1 },
  ETCUSDT: { binance: 'ETCUSDT', okx: 'ETC-USDT-SWAP', okxCtVal: 10 },
  ETHUSDT: { binance: 'ETHUSDT', okx: 'ETH-USDT-SWAP', okxCtVal: 0.1 },
  FILUSDT: { binance: 'FILUSDT', okx: 'FIL-USDT-SWAP', okxCtVal: 0.1 },
  FLOWUSDT: { binance: 'FLOWUSDT', okx: 'FLOW-USDT-SWAP', okxCtVal: 10 },
  GALAUSDT: { binance: 'GALAUSDT', okx: 'GALA-USDT-SWAP', okxCtVal: 10 },
  GMTUSDT: { binance: 'GMTUSDT', okx: 'GMT-USDT-SWAP', okxCtVal: 1 },
  GRTUSDT: { binance: 'GRTUSDT', okx: 'GRT-USDT-SWAP', okxCtVal: 10 },
  HBARUSDT: { binance: 'HBARUSDT', okx: 'HBAR-USDT-SWAP', okxCtVal: 100 },
  ICPUSDT: { binance: 'ICPUSDT', okx: 'ICP-USDT-SWAP', okxCtVal: 0.01 },
  ICXUSDT: { binance: 'ICXUSDT', okx: 'ICX-USDT-SWAP', okxCtVal: 10 },
  IMXUSDT: { binance: 'IMXUSDT', okx: 'IMX-USDT-SWAP', okxCtVal: 1 },
  IOTXUSDT: { binance: 'IOTXUSDT' },
  JASMYUSDT: { binance: 'JASMYUSDT' },
  JTOUSDT: { binance: 'JTOUSDT', okx: 'JTO-USDT-SWAP', okxCtVal: 1 },
  JUPUSDT: { binance: 'JUPUSDT', okx: 'JUP-USDT-SWAP', okxCtVal: 10 },
  KAVAUSDT: { binance: 'KAVAUSDT' },
  KNCUSDT: { binance: 'KNCUSDT' },
  KSMUSDT: { binance: 'KSMUSDT', okx: 'KSM-USDT-SWAP', okxCtVal: 0.1 },
  LDOUSDT: { binance: 'LDOUSDT', okx: 'LDO-USDT-SWAP', okxCtVal: 1 },
  LINKUSDT: { binance: 'LINKUSDT', okx: 'LINK-USDT-SWAP', okxCtVal: 1 },
  LPTUSDT: { binance: 'LPTUSDT', okx: 'LPT-USDT-SWAP', okxCtVal: 0.1 },
  LQTYUSDT: { binance: 'LQTYUSDT', okx: 'LQTY-USDT-SWAP', okxCtVal: 1 },
  LTCUSDT: { binance: 'LTCUSDT', okx: 'LTC-USDT-SWAP', okxCtVal: 1 },
  MASKUSDT: { binance: 'MASKUSDT', okx: 'MASK-USDT-SWAP', okxCtVal: 1 },
  MTLUSDT: { binance: 'MTLUSDT' },
  NEARUSDT: { binance: 'NEARUSDT', okx: 'NEAR-USDT-SWAP', okxCtVal: 10 },
  NEOUSDT: { binance: 'NEOUSDT', okx: 'NEO-USDT-SWAP', okxCtVal: 1 },
  OGNUSDT: { binance: 'OGNUSDT' },
  ONDOUSDT: { binance: 'ONDOUSDT', okx: 'ONDO-USDT-SWAP', okxCtVal: 10 },
  ONEUSDT: { binance: 'ONEUSDT', okx: 'ONE-USDT-SWAP', okxCtVal: 100 },
  OPUSDT: { binance: 'OPUSDT', okx: 'OP-USDT-SWAP', okxCtVal: 1 },
  PENDLEUSDT: { binance: 'PENDLEUSDT', okx: 'PENDLE-USDT-SWAP', okxCtVal: 1 },
  PEOPLEUSDT: { binance: 'PEOPLEUSDT', okx: 'PEOPLE-USDT-SWAP', okxCtVal: 100 },
  PEPEUSDT: { okx: 'PEPE-USDT-SWAP', okxCtVal: 10000000 },
  RLCUSDT: { binance: 'RLCUSDT' },
  RSRUSDT: { binance: 'RSRUSDT', okx: 'RSR-USDT-SWAP', okxCtVal: 100 },
  RUNEUSDT: { binance: 'RUNEUSDT' },
  SANDUSDT: { binance: 'SANDUSDT', okx: 'SAND-USDT-SWAP', okxCtVal: 10 },
  SEIUSDT: { binance: 'SEIUSDT', okx: 'SEI-USDT-SWAP', okxCtVal: 10 },
  SFPUSDT: { binance: 'SFPUSDT' },
  SKLUSDT: { binance: 'SKLUSDT' },
  SNXUSDT: { binance: 'SNXUSDT', okx: 'SNX-USDT-SWAP', okxCtVal: 1 },
  SOLUSDT: { binance: 'SOLUSDT', okx: 'SOL-USDT-SWAP', okxCtVal: 1 },
  STORJUSDT: { binance: 'STORJUSDT' },
  SUIUSDT: { binance: 'SUIUSDT', okx: 'SUI-USDT-SWAP', okxCtVal: 1 },
  SUSHIUSDT: { binance: 'SUSHIUSDT', okx: 'SUSHI-USDT-SWAP', okxCtVal: 1 },
  THETAUSDT: { binance: 'THETAUSDT', okx: 'THETA-USDT-SWAP', okxCtVal: 10 },
  TIAUSDT: { binance: 'TIAUSDT', okx: 'TIA-USDT-SWAP', okxCtVal: 1 },
  TRBUSDT: { binance: 'TRBUSDT', okx: 'TRB-USDT-SWAP', okxCtVal: 0.1 },
  TRXUSDT: { binance: 'TRXUSDT', okx: 'TRX-USDT-SWAP', okxCtVal: 1000 },
  UNIUSDT: { binance: 'UNIUSDT', okx: 'UNI-USDT-SWAP', okxCtVal: 1 },
  VETUSDT: { binance: 'VETUSDT' },
  WOOUSDT: { binance: 'WOOUSDT', okx: 'WOO-USDT-SWAP', okxCtVal: 10 },
  XLMUSDT: { binance: 'XLMUSDT', okx: 'XLM-USDT-SWAP', okxCtVal: 100 },
  XRPUSDT: { binance: 'XRPUSDT', okx: 'XRP-USDT-SWAP', okxCtVal: 100 },
  XTZUSDT: { binance: 'XTZUSDT', okx: 'XTZ-USDT-SWAP', okxCtVal: 1 },
  ZECUSDT: { binance: 'ZECUSDT', okx: 'ZEC-USDT-SWAP', okxCtVal: 0.01 },
  ZENUSDT: { binance: 'ZENUSDT', okx: 'ZEN-USDT-SWAP', okxCtVal: 0.1 },
  ZILUSDT: { binance: 'ZILUSDT', okx: 'ZIL-USDT-SWAP', okxCtVal: 100 },
  ZRXUSDT: { binance: 'ZRXUSDT', okx: 'ZRX-USDT-SWAP', okxCtVal: 10 },
};

const EXCHANGES = ['binance', 'okx'];

const REVERSE = new Map();
for (const [canonical, byExchange] of Object.entries(SYMBOL_MAP)) {
  for (const exchange of EXCHANGES) {
    if (byExchange[exchange]) REVERSE.set(`${exchange}:${byExchange[exchange]}`, canonical);
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

/** Canonical symbols (from `symbols`, default: every tracked symbol) that
 * have a live instrument mapping on `exchange`. */
export function symbolsFor(exchange, symbols = trackedSymbols()) {
  return symbols.filter((s) => Boolean(SYMBOL_MAP[s]?.[exchange]));
}

/**
 * OKX quotes SWAP order-book/trade quantity in number of contracts, not
 * base-asset units - `ctVal` (base-asset amount per contract) varies wildly
 * per instrument (0.01 for BTC, 10000000 for PEPE). Callers must multiply
 * raw OKX quantity by this before treating it as coin-denominated, or
 * cross-exchange notional/heatmap aggregation silently produces nonsense.
 */
export function okxContractValue(canonical) {
  return SYMBOL_MAP[canonical]?.okxCtVal ?? 1;
}
