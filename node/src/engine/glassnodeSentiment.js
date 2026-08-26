import { GlassnodeClient } from './glassnodeClient.js';

// ADD-ONLY module - mirrors forge/engine/glassnode_sentiment.py
// component for component, including the exact `glassnode` payload
// shape (snake_case keys, per the spec's contract) so a consumer gets
// the same shape regardless of which Forge service answered. Never
// imported by scoreEngine.js / liquidityEngine.js, and never feeds
// back into liquidityScore, the PDF §7 weights, the 1.15x wall bias
// threshold, or the confirmation confidence (connected/3).

const DIRECT_ASSETS = { BTCUSDT: 'BTC', ETHUSDT: 'ETH' };

// Candidate paths tried in order per component; the first one that
// returns data wins. Confirm against GET /v1/metadata/metrics?a=BTC if
// any of these start 404ing - Glassnode has renamed paths before.
const METRIC_PATHS = {
  sopr: ['/v1/metrics/indicators/sopr'],
  sth_sopr: ['/v1/metrics/indicators/sopr_less_155', '/v1/metrics/indicators/ssopr'],
  mvrv: ['/v1/metrics/market/mvrv'],
  sth_mvrv: ['/v1/metrics/market/mvrv_less_155'],
  nupl: ['/v1/metrics/indicators/net_unrealized_profit_loss', '/v1/metrics/market/nupl_more_155'],
  exch_netflow: [
    '/v1/metrics/distribution/exchange_net_position_change',
    '/v1/metrics/transactions/transfers_volume_exchanges_net',
  ],
  exch_reserve_d1: ['/v1/metrics/distribution/balance_exchanges'],
  stables: ['/v1/metrics/distribution/supply_stablecoins_sum'],
};

export const COMPONENT_KEYS = Object.keys(METRIC_PATHS); // exactly 8 - matches the max/cycle budget

// Heuristic calibration constants for the -100..+100 component scores.
// Directional lean formulas, not a validated trading model - tune once
// real series magnitudes are observed in production.
const NETFLOW_SATURATION_BTC = 2000.0;

function clamp(value, lo = -100, hi = 100) {
  return Math.max(lo, Math.min(hi, value));
}

function round(n, digits) {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

// SOPR > 1: coins moving on-chain in profit without panic (healthy) -> RISK_ON.
// SOPR < 1: realized losses / capitulation -> RISK_OFF.
export function scoreSopr(value) {
  return clamp((value - 1.0) * 400.0);
}

// ~1 = price at realized cost basis (neutral). Well below 1 =
// historically undervalued/accumulation (RISK_ON); well above ~3.5 =
// historically overheated/distribution (RISK_OFF).
export function scoreMvrv(value) {
  return clamp((1.0 - value) * 40.0);
}

// Glassnode NUPL zones: <0 capitulation, 0-.25 hope/fear, .25-.5
// optimism, .5-.75 belief, >.75 euphoria/greed. Centered on the
// belief/euphoria boundary.
export function scoreNupl(value) {
  return clamp((0.5 - value) * 200.0);
}

// Positive netflow = coins moving TO exchanges (sell pressure building) -> RISK_OFF.
// Negative netflow = coins leaving exchanges (accumulation) -> RISK_ON.
function scoreNetflow(value) {
  return clamp((-value / NETFLOW_SATURATION_BTC) * 100.0);
}

// Falling exchange reserves (negative %) = coins leaving custody -> RISK_ON.
function scoreReserveDeltaPct(pct) {
  return clamp(-pct * 20.0);
}

// Growing stablecoin supply = more on-chain dry powder -> RISK_ON.
function scoreStablesDeltaPct(pct) {
  return clamp(pct * 20.0);
}

/** % change between the last point and whichever prior point is
 * closest to `windowSeconds` before it (spacing depends on the
 * interval actually served, so this isn't literally points[-2]). */
function deltaPctOverSeconds(points, windowSeconds = 86400) {
  if (points.length < 2) return null;
  const last = points[points.length - 1];
  const targetT = last.t - windowSeconds;
  let prior = points[0];
  let bestDiff = Math.abs(prior.t - targetT);
  for (const p of points.slice(0, -1)) {
    const diff = Math.abs(p.t - targetT);
    if (diff < bestDiff) {
      bestDiff = diff;
      prior = p;
    }
  }
  if (prior.v === 0) return null;
  return ((last.v - prior.v) / Math.abs(prior.v)) * 100.0;
}

function valueScoreLast(scoreFn) {
  return (points) => {
    const v = points[points.length - 1].v;
    return [v, scoreFn(v)];
  };
}

function valueScoreReserveD1(points) {
  const pct = deltaPctOverSeconds(points);
  if (pct === null) return [null, null];
  return [pct, scoreReserveDeltaPct(pct)];
}

function valueScoreStables(points) {
  const pct = deltaPctOverSeconds(points);
  if (pct === null) return [null, null];
  return [points[points.length - 1].v, scoreStablesDeltaPct(pct)];
}

const VALUE_SCORE_FNS = {
  sopr: valueScoreLast(scoreSopr),
  sth_sopr: valueScoreLast(scoreSopr),
  mvrv: valueScoreLast(scoreMvrv),
  sth_mvrv: valueScoreLast(scoreMvrv),
  nupl: valueScoreLast(scoreNupl),
  exch_netflow: valueScoreLast(scoreNetflow),
  exch_reserve_d1: valueScoreReserveD1,
  stables: valueScoreStables,
};

function resolveAsset(symbol) {
  const direct = DIRECT_ASSETS[symbol.toUpperCase()];
  if (direct) return { asset: direct, assetDirect: true };
  // Alts anchor on the BTC on-chain layer instead of scanning the
  // Glassnode catalog at runtime.
  return { asset: 'BTC', assetDirect: false };
}

function emptyComponents() {
  const out = {};
  for (const k of COMPONENT_KEYS) out[k] = { value: null, score: null, avail: false };
  return out;
}

export function emptyGlassnodePayload(hasKey, notes = []) {
  return {
    has_key: hasKey,
    asof: Math.floor(Date.now() / 1000),
    asset_used: 'BTC',
    asset_direct: false,
    interval: '1h',
    glassnode_score: 0,
    glassnode_bias: 'NEUTRAL',
    glassnode_confidence: 0,
    components: emptyComponents(),
    notes,
  };
}

async function fetchComponent(client, key, asset, notes) {
  let intervalUsed = '1h';
  let lastNote = null;
  for (const path of METRIC_PATHS[key]) {
    // eslint-disable-next-line no-await-in-loop
    const result = await client.getMetric(path, asset, '1h');
    intervalUsed = result.interval;
    if (result.points) {
      const [value, score] = VALUE_SCORE_FNS[key](result.points);
      if (value !== null && score !== null) {
        return [{ value: round(value, 6), score: round(score, 2), avail: true }, intervalUsed];
      }
      lastNote = `${key}: not enough history for delta yet`;
      continue;
    }
    lastNote = `${key}: ${result.note}`;
  }
  if (lastNote) notes.push(lastNote);
  return [{ value: null, score: null, avail: false }, intervalUsed];
}

let clientSingleton = null;
function defaultClient() {
  if (!clientSingleton) clientSingleton = new GlassnodeClient();
  return clientSingleton;
}

/** Builds the `glassnode` sibling block for /api/score/:symbol. Never
 * throws - any failure (no key, bad key, network, rate limit) degrades
 * to has_key:false / avail:false components so the endpoint still
 * returns 200. */
export async function computeGlassnodeSentiment(symbol, client = defaultClient()) {
  const notes = [];

  if (!client.hasKey) return emptyGlassnodePayload(false, notes);

  const keyOk = await client.ensureKeyValid();
  if (!keyOk) {
    notes.push('glassnode unauthorized');
    return emptyGlassnodePayload(true, notes);
  }

  const { asset, assetDirect } = resolveAsset(symbol);
  let intervalUsed = '1h';
  const components = {};
  const scores = [];

  for (const key of COMPONENT_KEYS) {
    // eslint-disable-next-line no-await-in-loop
    const [comp, iv] = await fetchComponent(client, key, asset, notes);
    components[key] = comp;
    if (iv === '24h') intervalUsed = '24h';
    if (comp.avail && comp.score !== null) scores.push(comp.score);
  }

  const glassnodeScore = scores.length ? round(scores.reduce((a, b) => a + b, 0) / scores.length, 2) : 0;
  const confidence = round((scores.length / COMPONENT_KEYS.length) * 100, 1);
  let bias = 'NEUTRAL';
  if (scores.length) {
    if (glassnodeScore > 15) bias = 'RISK_ON';
    else if (glassnodeScore < -15) bias = 'RISK_OFF';
  }

  return {
    has_key: true,
    asof: Math.floor(Date.now() / 1000),
    asset_used: asset,
    asset_direct: assetDirect,
    interval: intervalUsed,
    glassnode_score: glassnodeScore,
    glassnode_bias: bias,
    glassnode_confidence: confidence,
    components,
    notes,
  };
}
