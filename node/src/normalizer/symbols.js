// Canonical symbol -> per-exchange instrument id (+ OKX's contract value,
// see below). Canonical keys follow Binance's own BASEUSDT ticker format
// (the scheme this codebase's API routes/tests already use), not the bare
// base asset. Extend this table when adding symbols or more exchanges.
//
// Generated from live Binance USDS-M futures, OKX SWAP, Bybit v5 linear
// and Bitget v2 USDT-FUTURES instrument lists (2026-08-13): every symbol
// below has a TRADING/live USDT perpetual on at least one of the four
// exchanges. Dropped from the requested list because no exchange has a
// live perpetual for them: LRC, NKN, SXP, TON (Binance lists TON/LRC/NKN
// but flagged SETTLING - being delisted - so excluded here too). BONK and
// PEPE only exist on Binance/Bybit under a 1000x-scaled ticker
// (1000BONKUSDT/1000PEPEUSDT) - deliberately not mapped there, since
// mixing a 1000x-scaled price/quantity with the other exchanges' plain
// ticker would need its own price-rescaling path; they stay on whichever
// of OKX/Bitget lists them at 1x.
const SYMBOL_MAP = {
  '1INCHUSDT': { binance: '1INCHUSDT', okx: '1INCH-USDT-SWAP', okxCtVal: 1, bybit: '1INCHUSDT', bitget: '1INCHUSDT' },
  ADAUSDT: { binance: 'ADAUSDT', okx: 'ADA-USDT-SWAP', okxCtVal: 100, bybit: 'ADAUSDT', bitget: 'ADAUSDT' },
  ALGOUSDT: { binance: 'ALGOUSDT', okx: 'ALGO-USDT-SWAP', okxCtVal: 10, bybit: 'ALGOUSDT', bitget: 'ALGOUSDT' },
  ALICEUSDT: { binance: 'ALICEUSDT', bybit: 'ALICEUSDT', bitget: 'ALICEUSDT' },
  ANKRUSDT: { binance: 'ANKRUSDT', bybit: 'ANKRUSDT', bitget: 'ANKRUSDT' },
  APEUSDT: { binance: 'APEUSDT', okx: 'APE-USDT-SWAP', okxCtVal: 0.1, bybit: 'APEUSDT', bitget: 'APEUSDT' },
  APTUSDT: { binance: 'APTUSDT', okx: 'APT-USDT-SWAP', okxCtVal: 1, bybit: 'APTUSDT', bitget: 'APTUSDT' },
  ARBUSDT: { binance: 'ARBUSDT', okx: 'ARB-USDT-SWAP', okxCtVal: 10, bybit: 'ARBUSDT', bitget: 'ARBUSDT' },
  ARPAUSDT: { binance: 'ARPAUSDT', bybit: 'ARPAUSDT', bitget: 'ARPAUSDT' },
  ARUSDT: { binance: 'ARUSDT', okx: 'AR-USDT-SWAP', okxCtVal: 0.1, bybit: 'ARUSDT', bitget: 'ARUSDT' },
  ATOMUSDT: { binance: 'ATOMUSDT', okx: 'ATOM-USDT-SWAP', okxCtVal: 1, bybit: 'ATOMUSDT', bitget: 'ATOMUSDT' },
  AVAXUSDT: { binance: 'AVAXUSDT', okx: 'AVAX-USDT-SWAP', okxCtVal: 1, bybit: 'AVAXUSDT', bitget: 'AVAXUSDT' },
  AXSUSDT: { binance: 'AXSUSDT', okx: 'AXS-USDT-SWAP', okxCtVal: 0.1, bybit: 'AXSUSDT', bitget: 'AXSUSDT' },
  BANDUSDT: { binance: 'BANDUSDT', okx: 'BAND-USDT-SWAP', okxCtVal: 1, bybit: 'BANDUSDT', bitget: 'BANDUSDT' },
  BATUSDT: { binance: 'BATUSDT', okx: 'BAT-USDT-SWAP', okxCtVal: 10, bybit: 'BATUSDT', bitget: 'BATUSDT' },
  BCHUSDT: { binance: 'BCHUSDT', okx: 'BCH-USDT-SWAP', okxCtVal: 0.1, bybit: 'BCHUSDT', bitget: 'BCHUSDT' },
  BELUSDT: { binance: 'BELUSDT', bybit: 'BELUSDT' },
  BNBUSDT: { binance: 'BNBUSDT', okx: 'BNB-USDT-SWAP', okxCtVal: 0.01, bybit: 'BNBUSDT', bitget: 'BNBUSDT' },
  BONKUSDT: { okx: 'BONK-USDT-SWAP', okxCtVal: 100000 },
  BTCUSDT: { binance: 'BTCUSDT', okx: 'BTC-USDT-SWAP', okxCtVal: 0.01, bybit: 'BTCUSDT', bitget: 'BTCUSDT' },
  CELOUSDT: { binance: 'CELOUSDT', okx: 'CELO-USDT-SWAP', okxCtVal: 1, bybit: 'CELOUSDT', bitget: 'CELOUSDT' },
  CHZUSDT: { binance: 'CHZUSDT', okx: 'CHZ-USDT-SWAP', okxCtVal: 10, bybit: 'CHZUSDT', bitget: 'CHZUSDT' },
  COMPUSDT: { binance: 'COMPUSDT', okx: 'COMP-USDT-SWAP', okxCtVal: 0.1, bybit: 'COMPUSDT', bitget: 'COMPUSDT' },
  COTIUSDT: { binance: 'COTIUSDT', bybit: 'COTIUSDT', bitget: 'COTIUSDT' },
  CYBERUSDT: { binance: 'CYBERUSDT', bybit: 'CYBERUSDT', bitget: 'CYBERUSDT' },
  DASHUSDT: { binance: 'DASHUSDT', okx: 'DASH-USDT-SWAP', okxCtVal: 0.01, bybit: 'DASHUSDT', bitget: 'DASHUSDT' },
  DOGEUSDT: { binance: 'DOGEUSDT', okx: 'DOGE-USDT-SWAP', okxCtVal: 1000, bybit: 'DOGEUSDT', bitget: 'DOGEUSDT' },
  DOTUSDT: { binance: 'DOTUSDT', okx: 'DOT-USDT-SWAP', okxCtVal: 1, bybit: 'DOTUSDT', bitget: 'DOTUSDT' },
  DUSKUSDT: { binance: 'DUSKUSDT', bybit: 'DUSKUSDT' },
  DYDXUSDT: { binance: 'DYDXUSDT', okx: 'DYDX-USDT-SWAP', okxCtVal: 1, bybit: 'DYDXUSDT', bitget: 'DYDXUSDT' },
  EGLDUSDT: { binance: 'EGLDUSDT', okx: 'EGLD-USDT-SWAP', okxCtVal: 0.1, bybit: 'EGLDUSDT', bitget: 'EGLDUSDT' },
  ENAUSDT: { binance: 'ENAUSDT', okx: 'ENA-USDT-SWAP', okxCtVal: 10, bybit: 'ENAUSDT', bitget: 'ENAUSDT' },
  ENJUSDT: { binance: 'ENJUSDT', okx: 'ENJ-USDT-SWAP', okxCtVal: 10, bybit: 'ENJUSDT', bitget: 'ENJUSDT' },
  ENSUSDT: { binance: 'ENSUSDT', okx: 'ENS-USDT-SWAP', okxCtVal: 0.1, bybit: 'ENSUSDT', bitget: 'ENSUSDT' },
  ETCUSDT: { binance: 'ETCUSDT', okx: 'ETC-USDT-SWAP', okxCtVal: 10, bybit: 'ETCUSDT', bitget: 'ETCUSDT' },
  ETHUSDT: { binance: 'ETHUSDT', okx: 'ETH-USDT-SWAP', okxCtVal: 0.1, bybit: 'ETHUSDT', bitget: 'ETHUSDT' },
  FILUSDT: { binance: 'FILUSDT', okx: 'FIL-USDT-SWAP', okxCtVal: 0.1, bybit: 'FILUSDT', bitget: 'FILUSDT' },
  FLOWUSDT: { binance: 'FLOWUSDT', okx: 'FLOW-USDT-SWAP', okxCtVal: 10, bybit: 'FLOWUSDT' },
  GALAUSDT: { binance: 'GALAUSDT', okx: 'GALA-USDT-SWAP', okxCtVal: 10, bybit: 'GALAUSDT', bitget: 'GALAUSDT' },
  GMTUSDT: { binance: 'GMTUSDT', okx: 'GMT-USDT-SWAP', okxCtVal: 1, bybit: 'GMTUSDT', bitget: 'GMTUSDT' },
  GRTUSDT: { binance: 'GRTUSDT', okx: 'GRT-USDT-SWAP', okxCtVal: 10, bybit: 'GRTUSDT', bitget: 'GRTUSDT' },
  HBARUSDT: { binance: 'HBARUSDT', okx: 'HBAR-USDT-SWAP', okxCtVal: 100, bybit: 'HBARUSDT', bitget: 'HBARUSDT' },
  ICPUSDT: { binance: 'ICPUSDT', okx: 'ICP-USDT-SWAP', okxCtVal: 0.01, bybit: 'ICPUSDT', bitget: 'ICPUSDT' },
  ICXUSDT: { binance: 'ICXUSDT', okx: 'ICX-USDT-SWAP', okxCtVal: 10, bybit: 'ICXUSDT', bitget: 'ICXUSDT' },
  IMXUSDT: { binance: 'IMXUSDT', okx: 'IMX-USDT-SWAP', okxCtVal: 1, bybit: 'IMXUSDT', bitget: 'IMXUSDT' },
  IOTXUSDT: { binance: 'IOTXUSDT', bybit: 'IOTXUSDT', bitget: 'IOTXUSDT' },
  JASMYUSDT: { binance: 'JASMYUSDT', bybit: 'JASMYUSDT', bitget: 'JASMYUSDT' },
  JTOUSDT: { binance: 'JTOUSDT', okx: 'JTO-USDT-SWAP', okxCtVal: 1, bybit: 'JTOUSDT', bitget: 'JTOUSDT' },
  JUPUSDT: { binance: 'JUPUSDT', okx: 'JUP-USDT-SWAP', okxCtVal: 10, bybit: 'JUPUSDT', bitget: 'JUPUSDT' },
  KAVAUSDT: { binance: 'KAVAUSDT', bybit: 'KAVAUSDT', bitget: 'KAVAUSDT' },
  KNCUSDT: { binance: 'KNCUSDT', bybit: 'KNCUSDT', bitget: 'KNCUSDT' },
  KSMUSDT: { binance: 'KSMUSDT', okx: 'KSM-USDT-SWAP', okxCtVal: 0.1, bybit: 'KSMUSDT', bitget: 'KSMUSDT' },
  LDOUSDT: { binance: 'LDOUSDT', okx: 'LDO-USDT-SWAP', okxCtVal: 1, bybit: 'LDOUSDT', bitget: 'LDOUSDT' },
  LINKUSDT: { binance: 'LINKUSDT', okx: 'LINK-USDT-SWAP', okxCtVal: 1, bybit: 'LINKUSDT', bitget: 'LINKUSDT' },
  LPTUSDT: { binance: 'LPTUSDT', okx: 'LPT-USDT-SWAP', okxCtVal: 0.1, bybit: 'LPTUSDT', bitget: 'LPTUSDT' },
  LQTYUSDT: { binance: 'LQTYUSDT', okx: 'LQTY-USDT-SWAP', okxCtVal: 1, bybit: 'LQTYUSDT', bitget: 'LQTYUSDT' },
  LTCUSDT: { binance: 'LTCUSDT', okx: 'LTC-USDT-SWAP', okxCtVal: 1, bybit: 'LTCUSDT', bitget: 'LTCUSDT' },
  MASKUSDT: { binance: 'MASKUSDT', okx: 'MASK-USDT-SWAP', okxCtVal: 1, bybit: 'MASKUSDT', bitget: 'MASKUSDT' },
  MTLUSDT: { binance: 'MTLUSDT', bybit: 'MTLUSDT', bitget: 'MTLUSDT' },
  NEARUSDT: { binance: 'NEARUSDT', okx: 'NEAR-USDT-SWAP', okxCtVal: 10, bybit: 'NEARUSDT', bitget: 'NEARUSDT' },
  NEOUSDT: { binance: 'NEOUSDT', okx: 'NEO-USDT-SWAP', okxCtVal: 1, bybit: 'NEOUSDT', bitget: 'NEOUSDT' },
  OGNUSDT: { binance: 'OGNUSDT', bybit: 'OGNUSDT', bitget: 'OGNUSDT' },
  ONDOUSDT: { binance: 'ONDOUSDT', okx: 'ONDO-USDT-SWAP', okxCtVal: 10, bybit: 'ONDOUSDT', bitget: 'ONDOUSDT' },
  ONEUSDT: { binance: 'ONEUSDT', okx: 'ONE-USDT-SWAP', okxCtVal: 100, bitget: 'ONEUSDT' },
  OPUSDT: { binance: 'OPUSDT', okx: 'OP-USDT-SWAP', okxCtVal: 1, bybit: 'OPUSDT', bitget: 'OPUSDT' },
  PENDLEUSDT: { binance: 'PENDLEUSDT', okx: 'PENDLE-USDT-SWAP', okxCtVal: 1, bybit: 'PENDLEUSDT', bitget: 'PENDLEUSDT' },
  PEOPLEUSDT: { binance: 'PEOPLEUSDT', okx: 'PEOPLE-USDT-SWAP', okxCtVal: 100, bybit: 'PEOPLEUSDT', bitget: 'PEOPLEUSDT' },
  PEPEUSDT: { okx: 'PEPE-USDT-SWAP', okxCtVal: 10000000, bitget: 'PEPEUSDT' },
  RLCUSDT: { binance: 'RLCUSDT', bybit: 'RLCUSDT' },
  RSRUSDT: { binance: 'RSRUSDT', okx: 'RSR-USDT-SWAP', okxCtVal: 100, bybit: 'RSRUSDT', bitget: 'RSRUSDT' },
  RUNEUSDT: { binance: 'RUNEUSDT', bybit: 'RUNEUSDT', bitget: 'RUNEUSDT' },
  SANDUSDT: { binance: 'SANDUSDT', okx: 'SAND-USDT-SWAP', okxCtVal: 10, bybit: 'SANDUSDT', bitget: 'SANDUSDT' },
  SEIUSDT: { binance: 'SEIUSDT', okx: 'SEI-USDT-SWAP', okxCtVal: 10, bybit: 'SEIUSDT', bitget: 'SEIUSDT' },
  SFPUSDT: { binance: 'SFPUSDT', bitget: 'SFPUSDT' },
  SKLUSDT: { binance: 'SKLUSDT', bybit: 'SKLUSDT', bitget: 'SKLUSDT' },
  SNXUSDT: { binance: 'SNXUSDT', okx: 'SNX-USDT-SWAP', okxCtVal: 1, bybit: 'SNXUSDT', bitget: 'SNXUSDT' },
  SOLUSDT: { binance: 'SOLUSDT', okx: 'SOL-USDT-SWAP', okxCtVal: 1, bybit: 'SOLUSDT', bitget: 'SOLUSDT' },
  STORJUSDT: { binance: 'STORJUSDT', bybit: 'STORJUSDT', bitget: 'STORJUSDT' },
  SUIUSDT: { binance: 'SUIUSDT', okx: 'SUI-USDT-SWAP', okxCtVal: 1, bybit: 'SUIUSDT', bitget: 'SUIUSDT' },
  SUSHIUSDT: { binance: 'SUSHIUSDT', okx: 'SUSHI-USDT-SWAP', okxCtVal: 1, bybit: 'SUSHIUSDT', bitget: 'SUSHIUSDT' },
  THETAUSDT: { binance: 'THETAUSDT', okx: 'THETA-USDT-SWAP', okxCtVal: 10, bybit: 'THETAUSDT', bitget: 'THETAUSDT' },
  TIAUSDT: { binance: 'TIAUSDT', okx: 'TIA-USDT-SWAP', okxCtVal: 1, bybit: 'TIAUSDT', bitget: 'TIAUSDT' },
  TRBUSDT: { binance: 'TRBUSDT', okx: 'TRB-USDT-SWAP', okxCtVal: 0.1, bybit: 'TRBUSDT', bitget: 'TRBUSDT' },
  TRXUSDT: { binance: 'TRXUSDT', okx: 'TRX-USDT-SWAP', okxCtVal: 1000, bybit: 'TRXUSDT', bitget: 'TRXUSDT' },
  UNIUSDT: { binance: 'UNIUSDT', okx: 'UNI-USDT-SWAP', okxCtVal: 1, bybit: 'UNIUSDT', bitget: 'UNIUSDT' },
  VETUSDT: { binance: 'VETUSDT', bybit: 'VETUSDT', bitget: 'VETUSDT' },
  WOOUSDT: { binance: 'WOOUSDT', okx: 'WOO-USDT-SWAP', okxCtVal: 10, bybit: 'WOOUSDT', bitget: 'WOOUSDT' },
  XLMUSDT: { binance: 'XLMUSDT', okx: 'XLM-USDT-SWAP', okxCtVal: 100, bybit: 'XLMUSDT', bitget: 'XLMUSDT' },
  XRPUSDT: { binance: 'XRPUSDT', okx: 'XRP-USDT-SWAP', okxCtVal: 100, bybit: 'XRPUSDT', bitget: 'XRPUSDT' },
  XTZUSDT: { binance: 'XTZUSDT', okx: 'XTZ-USDT-SWAP', okxCtVal: 1, bybit: 'XTZUSDT', bitget: 'XTZUSDT' },
  ZECUSDT: { binance: 'ZECUSDT', okx: 'ZEC-USDT-SWAP', okxCtVal: 0.01, bybit: 'ZECUSDT', bitget: 'ZECUSDT' },
  ZENUSDT: { binance: 'ZENUSDT', okx: 'ZEN-USDT-SWAP', okxCtVal: 0.1, bybit: 'ZENUSDT', bitget: 'ZENUSDT' },
  ZILUSDT: { binance: 'ZILUSDT', okx: 'ZIL-USDT-SWAP', okxCtVal: 100, bybit: 'ZILUSDT', bitget: 'ZILUSDT' },
  ZRXUSDT: { binance: 'ZRXUSDT', okx: 'ZRX-USDT-SWAP', okxCtVal: 10, bybit: 'ZRXUSDT', bitget: 'ZRXUSDT' },
};

const EXCHANGES = ['binance', 'okx', 'bybit', 'bitget'];

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
 * Binance, Bybit and Bitget all quote size directly in base-asset units
 * for the symbols mapped here, so no equivalent multiplier is needed for
 * them.
 */
export function okxContractValue(canonical) {
  return SYMBOL_MAP[canonical]?.okxCtVal ?? 1;
}
