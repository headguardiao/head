const BASE_URL = 'https://api.glassnode.com';
const CACHE_TTL_MS = 10 * 60 * 1000;
const KEY_CHECK_CACHE_MS = 24 * 60 * 60 * 1000;
const REQUEST_TIMEOUT_MS = 4000;
const KEY_CHECK_PATH = '/v1/metadata/metric';
const KEY_CHECK_QUERY_PATH = '/indicators/sopr';

/**
 * Thin cached client for the Glassnode metrics API. Mirrors
 * forge/engine/glassnode_client.py field for field - this is an add-on
 * sentiment data source only, nothing here is consumed by
 * scoreEngine.js's LIQUIDITY_SCORE pipeline.
 *
 * Every failure mode (missing key, 401/403, 429, network error,
 * timeout) resolves to `{ points: null, interval, note }` instead of
 * throwing, so callers can degrade to avail:false rather than crashing
 * the /api/score request.
 */
export class GlassnodeClient {
  constructor({ apiKey } = {}) {
    this.apiKey = apiKey !== undefined ? apiKey : (process.env.GLASSNODE_API_KEY || '');
    this._cache = new Map(); // "path|asset|interval" -> { fetchedAt, points }
    this._keyValid = null;
    this._keyCheckedAt = 0;
  }

  get hasKey() {
    return Boolean(this.apiKey);
  }

  /** One-shot (cached 24h) key validation via the cheapest possible
   * call (metric metadata, not a data series). Never throws. */
  async ensureKeyValid() {
    if (!this.hasKey) {
      this._keyValid = false;
      return false;
    }
    const now = Date.now();
    if (this._keyValid !== null && now - this._keyCheckedAt < KEY_CHECK_CACHE_MS) {
      return this._keyValid;
    }

    const url = new URL(KEY_CHECK_PATH, BASE_URL);
    url.searchParams.set('path', KEY_CHECK_QUERY_PATH);
    try {
      const res = await fetch(url, {
        headers: { 'X-Api-Key': this.apiKey },
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      this._keyValid = res.status === 200;
    } catch {
      this._keyCheckedAt = now;
      return false;
    }
    this._keyCheckedAt = now;
    return this._keyValid;
  }

  /** Fetch one metric series, cached 10 minutes per (path, asset,
   * interval). The BTC anchor layer is shared across every alt symbol
   * through this same cache key. */
  async getMetric(path, asset, interval = '1h') {
    if (!this.hasKey) return { points: null, interval, note: 'glassnode no api key' };

    const cacheKey = `${path}|${asset}|${interval}`;
    const cached = this._cache.get(cacheKey);
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
      return { points: cached.points, interval, note: cached.points ? null : 'glassnode cached miss' };
    }

    const result = await this._fetch(path, asset, interval);
    this._cache.set(cacheKey, { fetchedAt: Date.now(), points: result.points });
    return result;
  }

  async _fetch(path, asset, interval) {
    const now = Math.floor(Date.now() / 1000);
    const url = new URL(path, BASE_URL);
    url.searchParams.set('a', asset);
    url.searchParams.set('i', interval);
    url.searchParams.set('s', String(now - 7 * 24 * 3600));
    url.searchParams.set('u', String(now));
    url.searchParams.set('f', 'json');
    // Accepted for debug per spec; X-Api-Key header is the real auth.
    url.searchParams.set('api_key', this.apiKey);

    let res;
    try {
      res = await fetch(url, {
        headers: { 'X-Api-Key': this.apiKey },
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
    } catch {
      return { points: null, interval, note: 'glassnode request failed' };
    }

    if (res.status === 401 || res.status === 403) {
      this._keyValid = false;
      return { points: null, interval, note: 'glassnode unauthorized' };
    }
    if (res.status === 429) {
      return { points: null, interval, note: 'glassnode rate limit' };
    }
    if (res.status === 400 && interval === '1h') {
      return this._fetch(path, asset, '24h');
    }
    if (res.status === 404) {
      return { points: null, interval, note: 'glassnode metric not found' };
    }
    if (!res.ok) {
      return { points: null, interval, note: `glassnode http ${res.status}` };
    }

    let data;
    try {
      data = await res.json();
    } catch {
      return { points: null, interval, note: 'glassnode invalid json' };
    }
    if (!Array.isArray(data) || data.length === 0) {
      return { points: null, interval, note: 'glassnode empty series' };
    }
    return { points: data, interval, note: null };
  }
}
