import { OnchainClient } from './onchainClient.js';

// ADD-ONLY module (Camada D do briefing). Mirrors
// forge/engine/onchain_engine.py. Objeto irmão `onchain` em
// /api/score/:symbol. Sem Glassnode aqui (isso é Camada E, em
// glassnodeSentiment.js) - só mempool.space + DefiLlama, sem chave.
// Nunca toca liquidityScore, os pesos PDF §7, o bias de paredes ou
// confidence=exchanges/3.

// Alt -> chain DefiLlama. BTC e "meme coins" sem chain própria de TVL
// relevante usam só a camada global (btcFee/btcMempool/btcHashrate/
// stables7d/pegStress) - chainTvl1d e ethGas ficam avail:false.
const CHAIN_MAP = {
  ETHUSDT: 'Ethereum',
  ARBUSDT: 'Arbitrum',
  OPUSDT: 'Optimism',
  SOLUSDT: 'Solana',
  SUIUSDT: 'Sui',
  AVAXUSDT: 'Avalanche',
  BNBUSDT: 'BSC',
};

export const COMPONENT_KEYS = [
  'stables_7d',
  'chain_tvl_1d',
  'btc_fee',
  'btc_mempool',
  'peg_stress',
  'eth_gas',
  'btc_hashrate',
];

// Weights from the briefing's "Pesos 30m" table for Camada D; sum to
// 1.0. Renormalized over whichever components are avail (chainTvl1d
// and ethGas are structurally unavailable for BTC/meme symbols).
const WEIGHTS_30M = {
  stables_7d: 0.22,
  chain_tvl_1d: 0.18,
  btc_fee: 0.16,
  btc_mempool: 0.14,
  peg_stress: 0.14,
  eth_gas: 0.10,
  btc_hashrate: 0.06,
};

export const BIAS_THRESHOLD = 15;
const PEG_STRESS_BPS_THRESHOLD = 50;

// Heuristic calibration constants - the briefing gives weights and the
// peg-stress override rule but no exact per-component formula for
// Camada D (unlike Camada C). These are documented, tunable directional
// leans, not a validated model:
// - btcFee / btcMempool / ethGas: congestion proxies, treated as a
//   caution signal (RISK_OFF lean) when elevated. Tune the baselines
//   once real magnitudes are observed.
const BTC_FEE_BASELINE_SAT_VB = 20.0;
const BTC_FEE_SCALE = 3.0;
const BTC_MEMPOOL_BASELINE_COUNT = 5000.0;
const BTC_MEMPOOL_SCALE = 0.02;
const ETH_GAS_BASELINE_GWEI = 30.0;
const ETH_GAS_SCALE = 2.0;
const CHAIN_TVL_SCALE = 15.0;
const STABLES_SCALE = 10.0;
const HASHRATE_SCALE = 20.0;
const PEG_STRESS_SCALE = 2.0;

function clamp(value, lo = -100, hi = 100) {
  return Math.max(lo, Math.min(hi, value));
}

function round(n, digits) {
  const f = 10 ** digits;
  return Math.round(n * f) / f;
}

function component(value, score) {
  const avail = value !== null && value !== undefined && score !== null && score !== undefined;
  return { value: avail ? round(value, 6) : null, score: avail ? round(score, 2) : null, avail };
}

function pctChangeOverSeconds(series, windowSeconds) {
  if (series.length < 2) return null;
  const sorted = [...series].sort((a, b) => a[0] - b[0]);
  const [lastT, lastV] = sorted[sorted.length - 1];
  const targetT = lastT - windowSeconds;
  let prior = sorted[0];
  let bestDiff = Math.abs(prior[0] - targetT);
  for (const p of sorted.slice(0, -1)) {
    const diff = Math.abs(p[0] - targetT);
    if (diff < bestDiff) {
      bestDiff = diff;
      prior = p;
    }
  }
  const priorV = prior[1];
  if (priorV === 0) return null;
  return ((lastV - priorV) / Math.abs(priorV)) * 100.0;
}

function resolveChain(symbol) {
  return CHAIN_MAP[symbol.toUpperCase()] || null;
}

async function btcFee(client) {
  const data = await client.btcFeesRecommended();
  const fee = data?.fastestFee;
  if (fee === undefined || fee === null) return component(null, null);
  return component(fee, clamp(-(fee - BTC_FEE_BASELINE_SAT_VB) * BTC_FEE_SCALE));
}

async function btcMempool(client) {
  const data = await client.btcMempool();
  const count = data?.count;
  if (count === undefined || count === null) return component(null, null);
  return component(count, clamp(-(count - BTC_MEMPOOL_BASELINE_COUNT) * BTC_MEMPOOL_SCALE));
}

async function btcHashrate(client) {
  const data = await client.btcHashrate('3d');
  if (!Array.isArray(data?.hashrates)) return component(null, null);
  const points = data.hashrates
    .filter((p) => p.timestamp !== undefined && p.avgHashrate !== undefined)
    .map((p) => [Number(p.timestamp), Number(p.avgHashrate)]);
  const changePct = pctChangeOverSeconds(points, 3 * 24 * 3600);
  if (changePct === null) return component(null, null);
  // Rising hashrate = more security/commitment behind the network -> RISK_ON.
  return component(changePct, clamp(changePct * HASHRATE_SCALE));
}

async function chainTvl1d(client, symbol) {
  const chain = resolveChain(symbol);
  if (!chain) return component(null, null);
  const data = await client.historicalChainTvl(chain);
  if (!Array.isArray(data)) return component(null, null);
  const points = data.filter((p) => p.date !== undefined && p.tvl !== undefined).map((p) => [Number(p.date), Number(p.tvl)]);
  const changePct = pctChangeOverSeconds(points, 24 * 3600);
  if (changePct === null) return component(null, null);
  // Rising TVL = capital flowing into the chain -> RISK_ON.
  return component(changePct, clamp(changePct * CHAIN_TVL_SCALE));
}

async function stables7d(client) {
  const data = await client.stablecoinChartsAll();
  if (!Array.isArray(data)) return component(null, null);
  const points = data
    .filter((p) => p.date !== undefined && p.totalCirculating?.peggedUSD !== undefined)
    .map((p) => [Number(p.date), Number(p.totalCirculating.peggedUSD)]);
  const changePct = pctChangeOverSeconds(points, 7 * 24 * 3600);
  if (changePct === null) return component(null, null);
  // Growing aggregate stablecoin supply = more on-chain dry powder -> RISK_ON.
  return component(changePct, clamp(changePct * STABLES_SCALE));
}

async function pegStress(client) {
  const data = await client.stablecoinPrices();
  if (!Array.isArray(data)) return { comp: component(null, null), stressed: false };

  let worstBps = null;
  for (const entry of data) {
    const symbol = String(entry.symbol || '').toUpperCase();
    if ((symbol !== 'USDT' && symbol !== 'USDC') || entry.price === undefined) continue;
    const devBps = (Number(entry.price) - 1.0) * 10000.0;
    if (worstBps === null || Math.abs(devBps) > Math.abs(worstBps)) worstBps = devBps;
  }
  if (worstBps === null) return { comp: component(null, null), stressed: false };

  const stressed = Math.abs(worstBps) > PEG_STRESS_BPS_THRESHOLD;
  const score = clamp(-Math.abs(worstBps) * PEG_STRESS_SCALE);
  return { comp: component(worstBps, score), stressed };
}

async function ethGas(client) {
  const gwei = await client.ethGasPriceGwei();
  if (gwei === null) return component(null, null);
  return component(gwei, clamp(-(gwei - ETH_GAS_BASELINE_GWEI) * ETH_GAS_SCALE));
}

export function biasFromScore(score) {
  if (score >= BIAS_THRESHOLD) return 'RISK_ON';
  if (score <= -BIAS_THRESHOLD) return 'RISK_OFF';
  return 'NEUTRAL';
}

let clientSingleton = null;
function defaultClient() {
  if (!clientSingleton) clientSingleton = new OnchainClient();
  return clientSingleton;
}

/** Builds the Camada D `onchain` sibling block. Never throws - any
 * dead/blocked source (mempool.space, DefiLlama, the public ETH RPC)
 * resolves to avail:false for that component, never a 500. */
export async function computeOnchain(symbol, client = defaultClient()) {
  const notes = [];
  const upperSymbol = symbol.toUpperCase();
  // BTC and "meme" symbols (DOGE/PEPE/BONK/...) simply have no entry
  // in CHAIN_MAP - they use only the global components, per the briefing.
  const chain = resolveChain(upperSymbol);
  const isGlobalOnly = chain === null;

  const [stables7dComp, chainTvl1dComp, btcFeeComp, btcMempoolComp, pegResult, ethGasComp, btcHashrateComp] =
    await Promise.all([
      stables7d(client),
      isGlobalOnly ? Promise.resolve(component(null, null)) : chainTvl1d(client, upperSymbol),
      btcFee(client),
      btcMempool(client),
      pegStress(client),
      isGlobalOnly ? Promise.resolve(component(null, null)) : ethGas(client),
      btcHashrate(client),
    ]);

  if (pegResult.stressed) notes.push('stable peg stress');

  const components = {
    stables_7d: stables7dComp,
    chain_tvl_1d: chainTvl1dComp,
    btc_fee: btcFeeComp,
    btc_mempool: btcMempoolComp,
    peg_stress: pegResult.comp,
    eth_gas: ethGasComp,
    btc_hashrate: btcHashrateComp,
  };

  let weightedSum = 0;
  let weightTotal = 0;
  for (const key of COMPONENT_KEYS) {
    if (components[key].avail) {
      weightedSum += WEIGHTS_30M[key] * components[key].score;
      weightTotal += WEIGHTS_30M[key];
    }
  }

  const onchainScore = weightTotal > 0 ? round(weightedSum / weightTotal, 2) : 0;
  const availableCount = COMPONENT_KEYS.filter((k) => components[k].avail).length;
  const onchainConfidence = round((availableCount / COMPONENT_KEYS.length) * 100, 1);

  let onchainBias;
  if (weightTotal <= 0) onchainBias = 'NEUTRAL';
  else if (pegResult.stressed) onchainBias = 'RISK_OFF'; // spec: peg stress forces RISK_OFF regardless of the aggregate.
  else onchainBias = biasFromScore(onchainScore);

  return {
    symbol: upperSymbol,
    asof: Math.floor(Date.now() / 1000),
    chain_used: chain,
    onchain_score: onchainScore,
    onchain_bias: onchainBias,
    onchain_confidence: onchainConfidence,
    peg_stressed: pegResult.stressed,
    components,
    notes,
  };
}

/** Pure helper for the caller (the alerts app) that already knows the
 * side (LONG/SHORT). Not called automatically from /api/score - this
 * module has no "side" input of its own. Gated by FORGE_ONCHAIN_GATE
 * (default off); when off, always "allow". */
export function evaluateOnchainGate(onchainBias, pegStressed, confidence, side, enabled = null) {
  const isEnabled = enabled === null ? (process.env.FORGE_ONCHAIN_GATE || 'off').toLowerCase() === 'on' : enabled;
  if (!isEnabled) return 'allow';

  const upperSide = side.toUpperCase();
  if (pegStressed && upperSide === 'LONG') return 'block'; // spec: "Peg stress -> block LONG"
  if (onchainBias === 'NEUTRAL' && confidence >= 50) return 'reduce';
  return 'allow';
}
