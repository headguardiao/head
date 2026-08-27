// Public (no API key) client for mempool.space + DefiLlama, used by
// the Camada D on-chain layer. Mirrors forge/engine/onchain_client.py.
// Every source is independent and best-effort: a dead/blocked (e.g.
// 403) source resolves to `null`, never throws, so one broken endpoint
// can't take the whole `onchain` block down. Responses cached 60s.

const MEMPOOL_BASE = 'https://mempool.space/api';
const LLAMA_BASE = 'https://api.llama.fi';
const STABLECOINS_BASE = 'https://stablecoins.llama.fi';
// Cloudflare's public no-key Ethereum RPC gateway - used only for
// eth_gasPrice (best-effort; spec explicitly forbids requesting an
// Etherscan key).
const ETH_RPC_URL = 'https://cloudflare-eth.com';

const REQUEST_TIMEOUT_MS = 3000;
const CACHE_TTL_MS = 60000;

export class OnchainClient {
  constructor() {
    this._cache = new Map();
  }

  async _getJson(url) {
    const cached = this._cache.get(url);
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) return cached.data;

    let data = null;
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
      if (res.ok) data = await res.json();
    } catch {
      data = null;
    }
    this._cache.set(url, { fetchedAt: Date.now(), data });
    return data;
  }

  // ---- Bitcoin / global ---------------------------------------------
  async btcFeesRecommended() {
    return this._getJson(`${MEMPOOL_BASE}/v1/fees/recommended`);
  }

  async btcMempool() {
    return this._getJson(`${MEMPOOL_BASE}/mempool`);
  }

  async btcHashrate(period = '3d') {
    return this._getJson(`${MEMPOOL_BASE}/v1/mining/hashrate/${period}`);
  }

  // ---- DefiLlama chains / TVL ----------------------------------------
  async historicalChainTvl(chain) {
    return this._getJson(`${LLAMA_BASE}/v2/historicalChainTvl/${chain}`);
  }

  // ---- Stablecoins -----------------------------------------------------
  async stablecoinChartsAll() {
    return this._getJson(`${STABLECOINS_BASE}/stablecoincharts/all`);
  }

  async stablecoinPrices() {
    return this._getJson(`${STABLECOINS_BASE}/stablecoinprices`);
  }

  // ---- ETH gas (best-effort, no key) -----------------------------------
  async ethGasPriceGwei() {
    const cacheKey = 'eth_gasPrice';
    const cached = this._cache.get(cacheKey);
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) return cached.data;

    let gwei = null;
    try {
      const res = await fetch(ETH_RPC_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'eth_gasPrice', params: [], id: 1 }),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (res.ok) {
        const data = await res.json();
        if (data?.result) gwei = parseInt(data.result, 16) / 1e9;
      }
    } catch {
      gwei = null;
    }
    this._cache.set(cacheKey, { fetchedAt: Date.now(), data: gwei });
    return gwei;
  }
}
