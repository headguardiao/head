// Public (no API key) client for the Binance derivatives endpoints and
// Fear & Greed used by the Camada C sentiment layer. Mirrors
// forge/engine/sentiment_client.py. Every source is independent: a
// dead/slow source resolves to `null` for that one call, never throws,
// so one broken endpoint can't take the whole /api/sentiment response
// down. Responses cached 20-30s per (path, params).

// Same futures host the exchange adapters already use successfully -
// avoid fapi.binance.com only if an environment 451s it, in which case
// switch both here and there.
const FUTURES_BASE = 'https://fapi.binance.com';
const SPOT_BASE = 'https://api.binance.com';
const FNG_URL = 'https://api.alternative.me/fng/';

const REQUEST_TIMEOUT_MS = 2500;
const CACHE_TTL_MS = 25000;

export class SentimentClient {
  constructor() {
    this._cache = new Map(); // "base|path|params" -> { fetchedAt, data }
  }

  async _getJson(base, path, params = {}) {
    const url = new URL(path, base);
    for (const [k, v] of Object.entries(params)) url.searchParams.set(k, String(v));
    const cacheKey = url.toString();

    const cached = this._cache.get(cacheKey);
    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) return cached.data;

    let data = null;
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
      if (res.ok) data = await res.json();
    } catch {
      data = null;
    }
    this._cache.set(cacheKey, { fetchedAt: Date.now(), data });
    return data;
  }

  async premiumIndex(symbol) {
    return this._getJson(FUTURES_BASE, '/fapi/v1/premiumIndex', { symbol });
  }

  async fundingRateHistory(symbol, limit = 21) {
    return this._getJson(FUTURES_BASE, '/fapi/v1/fundingRate', { symbol, limit });
  }

  async globalLongShortRatio(symbol, period = '15m') {
    return this._getJson(FUTURES_BASE, '/futures/data/globalLongShortAccountRatio', { symbol, period, limit: 1 });
  }

  async topLongShortPositionRatio(symbol, period = '15m') {
    return this._getJson(FUTURES_BASE, '/futures/data/topLongShortPositionRatio', { symbol, period, limit: 1 });
  }

  async takerLongShortRatio(symbol, period) {
    return this._getJson(FUTURES_BASE, '/futures/data/takerlongshortRatio', { symbol, period, limit: 1 });
  }

  async openInterestHist(symbol, period = '15m', limit = 2) {
    return this._getJson(FUTURES_BASE, '/futures/data/openInterestHist', { symbol, period, limit });
  }

  // Not in the spec's source list verbatim, but needed to pair
  // openInterestHist with a comparable price change for oi_price_agree
  // - same public futures host, no key.
  async klines(symbol, interval = '15m', limit = 2) {
    return this._getJson(FUTURES_BASE, '/fapi/v1/klines', { symbol, interval, limit });
  }

  async ticker24hSpot(symbol) {
    return this._getJson(SPOT_BASE, '/api/v3/ticker/24hr', { symbol });
  }

  async fearGreed() {
    return this._getJson(FNG_URL, '', { limit: 2 });
  }
}
