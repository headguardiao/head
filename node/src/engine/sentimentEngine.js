import { SentimentClient } from './sentimentClient.js';

// ADD-ONLY module (Camada C do briefing). Mirrors
// forge/engine/sentiment_engine.py. Never imported by scoreEngine.js /
// liquidityEngine.js; never touches liquidityScore, the PDF §7
// weights, the 1.15x wall bias threshold, or confidence=exchanges/3.
// Sibling data source consumed through GET /api/sentiment/:symbol and
// an optional `sentiment` key on /api/score/:symbol.

export const COMPONENT_KEYS = [
  'funding_z',
  'basis_bps',
  'retail_ls',
  'whale_pos_ls',
  'taker_15m',
  'taker_shift',
  'oi_price_agree',
  'liq_side',
  'fng',
];

// fng is informational only ("só dashboard; peso 0 no 30m") - it's a
// tracked component (counts toward sentimentConfidence) but never part
// of the sentimentScore average.
const SCORED_COMPONENT_KEYS = COMPONENT_KEYS.filter((k) => k !== 'fng');

export const BIAS_THRESHOLD = 15;

// Heuristic calibration constant - oi_price_agree isn't given an exact
// scale in the spec ("mesmo sinal = a favor, sinais opostos = contra"),
// only the sign rule. Tune once real magnitudes are observed.
const OI_PRICE_AGREE_SCALE = 15.0;

function clamp(value, lo = -100, hi = 100) {
  return Math.max(lo, Math.min(hi, value));
}

function round(n, digits) {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

function component(value, score) {
  const avail = value !== null && value !== undefined && score !== null && score !== undefined;
  return {
    value: avail ? round(value, 6) : null,
    score: avail ? round(score, 2) : null,
    avail,
  };
}

async function fundingZ(client, symbol) {
  const history = await client.fundingRateHistory(symbol, 21);
  if (!Array.isArray(history) || history.length < 2) return component(null, null);
  const rates = history.map((r) => Number(r.fundingRate));
  if (rates.some(Number.isNaN)) return component(null, null);
  const mean = rates.reduce((a, b) => a + b, 0) / rates.length;
  const variance = rates.reduce((sum, r) => sum + (r - mean) ** 2, 0) / rates.length;
  const stdev = Math.sqrt(variance);
  const latest = rates[rates.length - 1];
  const z = stdev === 0 ? 0 : (latest - mean) / stdev;
  // funding alto (positivo) e fora do normal = mercado lotado de long -> RISK_OFF.
  return component(z, clamp(-z * 40.0));
}

async function basisBps(client, symbol) {
  const data = await client.premiumIndex(symbol);
  if (!data) return component(null, null);
  const mark = Number(data.markPrice);
  const index = Number(data.indexPrice);
  if (!index || Number.isNaN(mark) || Number.isNaN(index)) return component(null, null);
  const basis = ((mark - index) / index) * 10000.0;
  // premium (futuro acima do índice) = alavancagem otimista -> RISK_OFF.
  return component(basis, clamp(-basis * 2.0));
}

async function retailLs(client, symbol) {
  const data = await client.globalLongShortRatio(symbol);
  if (!Array.isArray(data) || !data.length) return component(null, null);
  const ratio = Number(data[data.length - 1].longShortRatio);
  if (Number.isNaN(ratio)) return component(null, null);
  return component(ratio, clamp((1.0 - ratio) * 80.0));
}

async function whalePosLs(client, symbol, notes) {
  const data = await client.topLongShortPositionRatio(symbol);
  if (!Array.isArray(data) || !data.length) return component(null, null);
  const ratio = Number(data[data.length - 1].longShortRatio);
  if (Number.isNaN(ratio)) return component(null, null);
  if (ratio > 2.0) notes.push('whale crowded long');
  return component(ratio, clamp((1.0 - ratio) * 60.0));
}

async function takerRatio(client, symbol, period) {
  const data = await client.takerLongShortRatio(symbol, period);
  if (!Array.isArray(data) || !data.length) return null;
  const ratio = Number(data[data.length - 1].buySellRatio);
  return Number.isNaN(ratio) ? null : ratio;
}

async function oiPriceAgree(client, symbol) {
  const [oiHist, candles] = await Promise.all([client.openInterestHist(symbol), client.klines(symbol)]);
  if (!Array.isArray(oiHist) || !Array.isArray(candles) || oiHist.length < 2 || candles.length < 2) {
    return component(null, null);
  }
  const oiStart = Number(oiHist[0].sumOpenInterestValue);
  const oiEnd = Number(oiHist[oiHist.length - 1].sumOpenInterestValue);
  const priceStart = Number(candles[0][1]); // open of the oldest candle
  const priceEnd = Number(candles[candles.length - 1][4]); // close of the newest candle
  if (!oiStart || !priceStart || [oiEnd, priceEnd].some(Number.isNaN)) return component(null, null);

  const oiChangePct = ((oiEnd - oiStart) / oiStart) * 100.0;
  const priceChangePct = ((priceEnd - priceStart) / priceStart) * 100.0;
  const magnitude = clamp((Math.abs(oiChangePct) + Math.abs(priceChangePct)) * OI_PRICE_AGREE_SCALE, 0, 100);
  const sameDirection = oiChangePct !== 0 && priceChangePct !== 0;
  const agree = (oiChangePct > 0) === (priceChangePct > 0);
  const score = agree && sameDirection ? magnitude : -magnitude;
  return component(oiChangePct, score);
}

function liqSide(state) {
  if (!state) return component(null, null);
  const liquidations = state.liquidations || [];
  if (!liquidations.length) return component(null, null);
  // event.side is the side of the FORCED order (as ingested from
  // Bybit/Binance/OKX liquidation feeds) - 'sell' closes a long, 'buy'
  // closes a short.
  const longNotional = liquidations.filter((l) => l.side === 'sell').reduce((sum, l) => sum + l.notionalUsd, 0);
  const shortNotional = liquidations.filter((l) => l.side === 'buy').reduce((sum, l) => sum + l.notionalUsd, 0);
  const total = longNotional + shortNotional;
  if (total === 0) return component(null, null);
  const raw = (longNotional - shortNotional) / total;
  // raw > 0 = mais notional de LONG liquidado = RISK_OFF -> score negativo.
  return component(raw, clamp(-raw * 100.0));
}

async function fng(client) {
  const data = await client.fearGreed();
  const raw = Number(data?.data?.[0]?.value);
  if (Number.isNaN(raw)) return component(null, null);
  return component(raw, clamp((50.0 - raw) * 2.0));
}

export function biasFromScore(score) {
  if (score >= BIAS_THRESHOLD) return 'RISK_ON';
  if (score <= -BIAS_THRESHOLD) return 'RISK_OFF';
  return 'NEUTRAL';
}

async function computeOne(symbol, client, state) {
  const notes = [];

  const [fundingZComp, basisBpsComp, retailLsComp, whalePosLsComp, taker15mRatio, taker1hRatio, oiPriceAgreeComp, fngComp] =
    await Promise.all([
      fundingZ(client, symbol),
      basisBps(client, symbol),
      retailLs(client, symbol),
      whalePosLs(client, symbol, notes),
      takerRatio(client, symbol, '15m'),
      takerRatio(client, symbol, '1h'),
      oiPriceAgree(client, symbol),
      fng(client),
    ]);

  const taker15m =
    taker15mRatio === null ? component(null, null) : component(taker15mRatio, clamp((taker15mRatio - 1.0) * 100.0));

  let takerShift;
  if (taker15mRatio === null || taker1hRatio === null) {
    takerShift = component(null, null);
  } else {
    const shift = taker15mRatio - taker1hRatio;
    takerShift = component(shift, clamp(shift * 150.0));
  }

  const components = {
    funding_z: fundingZComp,
    basis_bps: basisBpsComp,
    retail_ls: retailLsComp,
    whale_pos_ls: whalePosLsComp,
    taker_15m: taker15m,
    taker_shift: takerShift,
    oi_price_agree: oiPriceAgreeComp,
    liq_side: liqSide(state),
    fng: fngComp,
  };

  const scores = SCORED_COMPONENT_KEYS.filter((k) => components[k].avail).map((k) => components[k].score);
  const sentimentScore = scores.length ? round(scores.reduce((a, b) => a + b, 0) / scores.length, 2) : 0;
  const availableCount = COMPONENT_KEYS.filter((k) => components[k].avail).length;
  const sentimentConfidence = round((availableCount / COMPONENT_KEYS.length) * 100, 1);
  const sentimentBias = scores.length ? biasFromScore(sentimentScore) : 'NEUTRAL';

  return {
    symbol,
    asof: Math.floor(Date.now() / 1000),
    sentiment_score: sentimentScore,
    sentiment_bias: sentimentBias,
    sentiment_confidence: sentimentConfidence,
    components,
    notes,
  };
}

let clientSingleton = null;
function defaultClient() {
  if (!clientSingleton) clientSingleton = new SentimentClient();
  return clientSingleton;
}

/** Builds the Camada C sentiment payload. Never throws - any dead
 * source resolves to avail:false for that one component, never a 500.
 * `marketStates` (the same Map index.js already builds) is optional
 * and only used to reuse already-ingested liquidations for liq_side -
 * never to recompute anything from scoreEngine.js. */
export async function computeSentiment(symbol, client = defaultClient(), marketStates = new Map()) {
  const upperSymbol = symbol.toUpperCase();
  const result = await computeOne(upperSymbol, client, marketStates.get(upperSymbol));

  if (upperSymbol === 'BTCUSDT') {
    result.btc_anchor = { score: result.sentiment_score, bias: result.sentiment_bias };
    return result;
  }

  const btcResult = await computeOne('BTCUSDT', client, marketStates.get('BTCUSDT'));
  result.btc_anchor = { score: btcResult.sentiment_score, bias: btcResult.sentiment_bias };
  const biasSet = new Set([result.sentiment_bias, btcResult.sentiment_bias]);
  if (biasSet.has('RISK_ON') && biasSet.has('RISK_OFF')) {
    result.notes.push(`${upperSymbol} ${result.sentiment_bias} but BTC anchor ${btcResult.sentiment_bias}`);
  }
  return result;
}

/** Pure helper for the caller (the alerts app) that already knows
 * which side (LONG/SHORT) it wants to take. Not called automatically
 * from /api/sentiment or /api/score - this module has no "side" input
 * of its own. Gated by FORGE_SENTIMENT_GATE (default off); when off,
 * always "allow" regardless of the numbers. */
export function evaluateSentimentGate(sentimentScore, sentimentConfidence, side, enabled = null) {
  const isEnabled = enabled === null ? (process.env.FORGE_SENTIMENT_GATE || 'off').toLowerCase() === 'on' : enabled;
  if (!isEnabled) return 'allow';

  const bias = biasFromScore(sentimentScore);
  const upperSide = side.toUpperCase();
  if (upperSide === 'LONG' && bias === 'RISK_OFF' && Math.abs(sentimentScore) >= 25) return 'block';
  if (upperSide === 'SHORT' && bias === 'RISK_ON' && Math.abs(sentimentScore) >= 25) return 'block';
  if (bias === 'NEUTRAL' && sentimentConfidence >= 50) return 'reduce';
  return 'allow';
}
