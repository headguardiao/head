import { GlassnodeClient } from './glassnodeClient.js';

// ADD-ONLY module - mirrors forge/engine/glassnode_sentiment.py
// component for component, including the exact `glassnode` payload
// shape (snake_case keys, per the spec's contract) so a consumer gets
// the same shape regardless of which Forge service answered. Never
// imported by scoreEngine.js / liquidityEngine.js, and never feeds
// back into liquidityScore, the PDF §7 weights, the 1.15x wall bias
// threshold, or the confirmation confidence (connected/3).
//
// Sign convention (per the calibrated briefing spec): positivo =
// RISK_ON = acumulação / reserva saindo da exchange / gasto no
// prejuízo (capitulation spend is a contrarian accumulation signal,
// NOT fear) - don't "fix" the signs below without re-reading this.

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

export const BIAS_THRESHOLD = 15;

// Weight profiles - priors calibrated on the operational (briefing
// section E), kept as data instead of inline in the formulas so they
// can be retuned without touching the scoring code. Selected via
// FORGE_SENTIMENT_PROFILE=30m|2h|daily (default 30m).
const WEIGHT_PROFILES = {
  '30m': {
    exch_netflow: 0.26,
    sth_sopr: 0.22,
    exch_reserve_d1: 0.14,
    sth_mvrv: 0.14,
    sopr: 0.10,
    mvrv: 0.06,
    nupl: 0.05,
    stables: 0.03,
  },
  '2h': {
    mvrv: 0.18,
    exch_netflow: 0.16,
    sopr: 0.14,
    sth_sopr: 0.14,
    nupl: 0.14,
    sth_mvrv: 0.10,
    exch_reserve_d1: 0.10,
    stables: 0.04,
  },
};
WEIGHT_PROFILES.daily = WEIGHT_PROFILES['2h']; // spec: "Perfil 2h/daily (regime)" - same table

function activeProfile() {
  const profile = process.env.FORGE_SENTIMENT_PROFILE || '30m';
  return WEIGHT_PROFILES[profile] ? profile : '30m';
}

function clamp(value, lo = -100, hi = 100) {
  return Math.max(lo, Math.min(hi, value));
}

function round(n, digits) {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

export function biasFromScore(score) {
  if (score >= BIAS_THRESHOLD) return 'RISK_ON';
  if (score <= -BIAS_THRESHOLD) return 'RISK_OFF';
  return 'NEUTRAL';
}

/** Nearest-rank percentile - good enough for a normalization
 * reference, not a statistical claim. */
function percentile(values, pct) {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  const idx = Math.max(0, Math.min(ordered.length - 1, Math.ceil((pct / 100) * ordered.length) - 1));
  return ordered[idx];
}

/** Sem lookahead: quando o chamador (o alerta) passa closeTime, só
 * pontos com t <= closeTime entram na leitura. */
function filterUpTo(points, closeTime) {
  if (closeTime === null || closeTime === undefined) return points;
  return points.filter((p) => p.t <= closeTime);
}

export function scoreSopr(value, notes = []) {
  if (value > 1.05) notes.push('sopr: profit taking');
  else if (value < 0.98) notes.push('sopr: capitulation spend');
  return clamp((1.0 - value) * 400.0);
}

export function scoreSthSopr(value) {
  return clamp((1.0 - value) * 350.0);
}

export function scoreMvrv(value, notes = []) {
  if (value >= 2.4) notes.push('mvrv: euphoria');
  else if (value <= 0.85) notes.push('mvrv: fear');
  return clamp((1.2 - value) * 50.0);
}

export function scoreSthMvrv(value) {
  return clamp((1.0 - value) * 80.0);
}

export function scoreNupl(value) {
  return clamp((0.25 - value) * 200.0);
}

// Falling exchange reserves (negative %) = coins leaving custody -> RISK_ON.
function scoreReserveDeltaPct(pct) {
  return clamp(-pct * 40.0);
}

// Growing stablecoin supply = more on-chain dry powder -> RISK_ON.
function scoreStablesDeltaPct(pct) {
  return clamp(pct * 12.0);
}

/** % change between the last point and whichever prior point is
 * closest to `windowSeconds` before it (spacing depends on the
 * interval actually served, so this isn't literally points[-2]). */
function deltaPctOverSeconds(points, windowSeconds) {
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

function valueScoreSopr(points, notes) {
  const v = points[points.length - 1].v;
  return [v, scoreSopr(v, notes)];
}

function valueScoreSthSopr(points) {
  const v = points[points.length - 1].v;
  return [v, scoreSthSopr(v)];
}

function valueScoreMvrv(points, notes) {
  const v = points[points.length - 1].v;
  return [v, scoreMvrv(v, notes)];
}

function valueScoreSthMvrv(points) {
  const v = points[points.length - 1].v;
  return [v, scoreSthMvrv(v)];
}

function valueScoreNupl(points) {
  const v = points[points.length - 1].v;
  return [v, scoreNupl(v)];
}

function valueScoreNetflow(points) {
  // "normalizar por p90 dos últimos 7 pontos" - literally the last 7
  // points of whatever series/interval Glassnode actually served.
  const latest = points[points.length - 1].v;
  const window = points.slice(-7);
  const p90 = percentile(window.map((p) => Math.abs(p.v)), 90);
  if (!p90) return [null, null];
  // Positive netflow (inflow to exchanges) = RISK_OFF.
  return [latest, clamp((-latest / p90) * 80.0)];
}

function valueScoreReserveD1(points) {
  const pct = deltaPctOverSeconds(points, 24 * 3600);
  if (pct === null) return [null, null];
  return [pct, scoreReserveDeltaPct(pct)];
}

function valueScoreStables(points) {
  const pct = deltaPctOverSeconds(points, 7 * 24 * 3600);
  if (pct === null) return [null, null];
  return [points[points.length - 1].v, scoreStablesDeltaPct(pct)];
}

const VALUE_SCORE_FNS = {
  sopr: valueScoreSopr,
  sth_sopr: valueScoreSthSopr,
  mvrv: valueScoreMvrv,
  sth_mvrv: valueScoreSthMvrv,
  nupl: valueScoreNupl,
  exch_netflow: valueScoreNetflow,
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
    profile: activeProfile(),
    glassnode_score: 0,
    glassnode_bias: 'NEUTRAL',
    glassnode_confidence: 0,
    components: emptyComponents(),
    notes,
  };
}

async function fetchComponent(client, key, asset, notes, closeTime) {
  let intervalUsed = '1h';
  let lastNote = null;
  for (const path of METRIC_PATHS[key]) {
    // eslint-disable-next-line no-await-in-loop
    const result = await client.getMetric(path, asset, '1h');
    intervalUsed = result.interval;
    const points = result.points ? filterUpTo(result.points, closeTime) : result.points;
    if (points && points.length) {
      const [value, score] = VALUE_SCORE_FNS[key](points, notes);
      if (value !== null && score !== null) {
        return [{ value: round(value, 6), score: round(score, 2), avail: true }, intervalUsed];
      }
      lastNote = `${key}: not enough history for delta yet`;
      continue;
    }
    lastNote = `${key}: ${result.note || 'no points up to closeTime'}`;
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
 * returns 200.
 *
 * `closeTime` (unix seconds, optional) is unused by /api/score itself
 * (no "alert" concept there) - it exists so a caller with a real alert
 * timestamp (the alerts app) can pass it for a lookahead-safe read. */
export async function computeGlassnodeSentiment(symbol, client = defaultClient(), closeTime = null) {
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

  for (const key of COMPONENT_KEYS) {
    // eslint-disable-next-line no-await-in-loop
    const [comp, iv] = await fetchComponent(client, key, asset, notes, closeTime);
    components[key] = comp;
    if (iv === '24h') intervalUsed = '24h';
  }

  const profile = activeProfile();
  const weights = WEIGHT_PROFILES[profile];
  let weightedSum = 0;
  let weightTotal = 0;
  for (const key of COMPONENT_KEYS) {
    const comp = components[key];
    if (comp.avail) {
      weightedSum += weights[key] * comp.score;
      weightTotal += weights[key];
    }
  }

  const glassnodeScore = weightTotal > 0 ? round(weightedSum / weightTotal, 2) : 0;
  const availableCount = COMPONENT_KEYS.filter((k) => components[k].avail).length;
  const confidence = round((availableCount / COMPONENT_KEYS.length) * 100, 1);
  const bias = weightTotal > 0 ? biasFromScore(glassnodeScore) : 'NEUTRAL';

  return {
    has_key: true,
    asof: Math.floor(Date.now() / 1000),
    asset_used: asset,
    asset_direct: assetDirect,
    interval: intervalUsed,
    profile,
    glassnode_score: glassnodeScore,
    glassnode_bias: bias,
    glassnode_confidence: confidence,
    components,
    notes,
  };
}

/** Pure helper for the caller (the alerts app) that already knows the
 * side (LONG/SHORT). Not called automatically from /api/score. Gated
 * by GLASSNODE_GATE (default off; when off, always "allow"). Implements
 * the asymmetric long/short rules from the briefing - long has two
 * independent ways to get blocked, short only one. */
export function evaluateGlassnodeGate(components, glassnodeScore, glassnodeConfidence, side, enabled = null) {
  const isEnabled = enabled === null ? (process.env.GLASSNODE_GATE || 'off').toLowerCase() === 'on' : enabled;
  if (!isEnabled) return 'allow';

  const upperSide = side.toUpperCase();
  const val = (key) => components[key]?.value ?? null;
  const score = (key) => components[key]?.score ?? null;

  if (upperSide === 'LONG') {
    if (glassnodeScore <= -12) return 'block';
    const soprV = val('sopr');
    const sthMvrvV = val('sth_mvrv');
    const mvrvV = val('mvrv');
    const netflowScore = score('exch_netflow');
    const condProfitDistribution = soprV !== null && sthMvrvV !== null && soprV > 1.05 && sthMvrvV > 1.2;
    const condEuphoria = mvrvV !== null && mvrvV >= 2.4;
    const condNetflow = netflowScore !== null && netflowScore <= -50;
    if (condProfitDistribution || condEuphoria || condNetflow) return 'block';
  } else if (upperSide === 'SHORT') {
    if (glassnodeScore >= 28) return 'block';
    const sthSoprV = val('sth_sopr');
    const netflowScore = score('exch_netflow');
    if (sthSoprV !== null && netflowScore !== null && sthSoprV < 0.97 && netflowScore >= 50) return 'block';
  }

  const bias = biasFromScore(glassnodeScore);
  if (bias === 'NEUTRAL' && glassnodeConfidence >= 50) return 'reduce';
  return 'allow';
}
