import { ExchangeAdapter } from '../base/ExchangeAdapter.js';
import { LocalOrderBook } from '../../engine/localOrderBook.js';
import { canonicalFromExchange, exchangeSymbol } from '../../normalizer/symbols.js';
import { notionalUsd } from '../../normalizer/notional.js';
import { validateOrderBookEvent, validateTradeEvent } from '../../normalizer/validate.js';
import { env } from '../../config/env.js';
import { logger } from '../../config/logger.js';
import { hasSequenceGap } from './sequence.js';

const WS_BASE = 'wss://fstream.binance.com';
const REST_BASE = 'https://fapi.binance.com';
// Back off between REST resync attempts for a symbol - the very first
// version of this adapter (in the Python sibling project) fired a fresh
// REST snapshot request on every buffered depth event (~10/s) while
// unsynced and got the test IP rate-limited/banned by Binance within
// seconds. One attempt in flight at a time avoids that outright, but a
// *fixed* retry interval still has a real cost: Binance counts a
// rejected (429) request's weight too, so retrying at a constant 5s
// cadence while throttled keeps consuming the budget that needs to
// recover - observed live as bursts of 429s separated by ever-longer
// gaps. Exponential backoff (capped) lets the budget actually drain.
const SYNC_BACKOFF_BASE_MS = 5000;
const SYNC_BACKOFF_MAX_MS = 60_000;
// With many symbols tracked, every one of them buffers its first depth
// event at roughly the same moment right after connecting, so without a
// cap here they'd all fire their REST snapshot request in the same tick -
// the exact burst pattern that got the test IP rate-limited/banned before
// (see the README's "Validado em teste ao vivo" section). Capping
// concurrent in-flight snapshot fetches spreads that burst out over a few
// seconds as slots free up instead of hitting Binance all at once.
const MAX_CONCURRENT_SYNCS = 4;
// The concurrency cap alone still lets requests fire back-to-back as
// slots free up (4 fast 429s can complete in well under a second), which
// at 90+ symbols burns through Binance's request-weight budget in
// seconds and re-triggers the exact IP-level throttle/ban this is meant
// to avoid - observed live: every symbol's sync stuck failing minutes
// after connecting, not just slow to catch up. A minimum gap between the
// *start* of successive REST calls (independent of concurrency) caps the
// aggregate rate directly: 1 req/s * weight 20 = 1200/min, half of
// Binance's 2400/min budget, leaving headroom for retries and (later)
// funding/OI polling.
const MIN_SYNC_INTERVAL_MS = 1000;
// Bounded so an extended throttle/outage can't grow this without limit -
// ~50s of buffered depth events at the ~100ms stream cadence, comfortably
// more than any realistic REST round trip once synced.
const MAX_BUFFERED_EVENTS = 500;

export class BinanceAdapter extends ExchangeAdapter {
  constructor({ symbols }) {
    super({ name: 'binance', symbols });
    this.books = new Map(symbols.map((s) => [s, new LocalOrderBook({ maxLevels: env.orderBookDepth })]));
    this.buffers = new Map(symbols.map((s) => [s, []]));
    this.synced = new Map(symbols.map((s) => [s, false]));
    this.syncInFlight = new Map(symbols.map((s) => [s, false]));
    this.nextSyncAttemptAt = new Map(symbols.map((s) => [s, 0]));
    this.syncFailureCount = new Map(symbols.map((s) => [s, 0]));
    this.lastUpdateId = new Map(symbols.map((s) => [s, 0]));
    this._activeSyncs = 0;
    this._lastSyncStartedAt = 0;
    this._lastSyncError = null;
  }

  /** Per-symbol sync state, surfaced on /health to diagnose "why is this
   * symbol missing from the aggregated book" without needing log access. */
  diagnostics() {
    const symbols = {};
    for (const s of this.symbols) {
      symbols[s] = {
        synced: this.synced.get(s) ?? false,
        syncFailureCount: this.syncFailureCount.get(s) ?? 0,
        bufferedEvents: this.buffers.get(s)?.length ?? 0,
      };
    }
    // A single shared error is enough context here: a failing REST snapshot
    // fetch is almost always an IP-level throttle/ban, which fails every
    // symbol for the same reason at once rather than symbol-by-symbol.
    return { symbols, lastError: this._lastSyncError };
  }

  getWsUrl() {
    const streams = this.symbols.flatMap((s) => {
      const sym = exchangeSymbol(s, 'binance').toLowerCase();
      return [`${sym}@depth@100ms`, `${sym}@aggTrade`];
    });
    return `${WS_BASE}/stream?streams=${streams.join('/')}`;
  }

  start() {
    for (const s of this.symbols) {
      this.buffers.set(s, []);
      this.synced.set(s, false);
    }
    super.start();
  }

  handleMessage(raw) {
    const msg = JSON.parse(raw.toString());
    const stream = msg.stream ?? '';
    const data = msg.data ?? {};
    if (stream.endsWith('@aggTrade')) {
      this._handleTrade(data);
    } else if (stream.includes('@depth')) {
      this._handleDepth(data);
    }
  }

  _handleTrade(data) {
    const canonical = canonicalFromExchange('binance', data.s);
    if (!canonical) return;
    const price = Number(data.p);
    const quantity = Number(data.q);
    const event = {
      eventType: 'trade',
      exchange: this.name,
      symbol: canonical,
      marketType: 'perpetual',
      price,
      quantity,
      notionalUsd: notionalUsd(price, quantity),
      side: data.m ? 'sell' : 'buy',
      timestamp: data.T,
      sequence: data.a,
    };
    try {
      this.emit('trade', validateTradeEvent(event));
    } catch (err) {
      logger.error(`[binance] invalid trade event: ${err.message}`);
    }
  }

  _handleDepth(data) {
    const canonical = canonicalFromExchange('binance', data.s);
    if (!canonical) return;

    if (!this.synced.get(canonical)) {
      const buffer = this.buffers.get(canonical);
      buffer.push(data);
      if (buffer.length > MAX_BUFFERED_EVENTS) {
        buffer.splice(0, buffer.length - MAX_BUFFERED_EVENTS);
      }
      this._maybeSync(canonical);
      return;
    }

    if (hasSequenceGap(data, this.lastUpdateId.get(canonical))) {
      logger.warn(
        `[binance] ${canonical} sequence gap (pu=${data.pu} expected=${this.lastUpdateId.get(canonical)}), resyncing`,
      );
      this.synced.set(canonical, false);
      this.buffers.set(canonical, [data]);
      this._maybeSync(canonical);
      return;
    }

    this._applyUpdate(canonical, data);
  }

  _maybeSync(canonical) {
    if (this.syncInFlight.get(canonical)) return;
    if (Date.now() < this.nextSyncAttemptAt.get(canonical)) return;
    const sinceLastStart = Date.now() - this._lastSyncStartedAt;
    if (sinceLastStart < MIN_SYNC_INTERVAL_MS) {
      this.nextSyncAttemptAt.set(canonical, this._lastSyncStartedAt + MIN_SYNC_INTERVAL_MS);
      return;
    }
    if (this._activeSyncs >= MAX_CONCURRENT_SYNCS) {
      // At capacity - retry shortly with jitter so the whole batch doesn't
      // wake up and re-contend for a slot in lockstep.
      this.nextSyncAttemptAt.set(canonical, Date.now() + 250 + Math.random() * 250);
      return;
    }
    this._activeSyncs += 1;
    this._lastSyncStartedAt = Date.now();
    this._trySync(canonical)
      .catch((err) => {
        logger.error(`[binance] ${canonical} resync failed: ${err.message}`);
        this._backoffNextSync(canonical);
      })
      .finally(() => {
        this._activeSyncs -= 1;
      });
  }

  _backoffNextSync(canonical) {
    const failures = (this.syncFailureCount.get(canonical) ?? 0) + 1;
    this.syncFailureCount.set(canonical, failures);
    const delay = Math.min(SYNC_BACKOFF_BASE_MS * 2 ** (failures - 1), SYNC_BACKOFF_MAX_MS);
    this.nextSyncAttemptAt.set(canonical, Date.now() + delay);
  }

  async _trySync(canonical) {
    const symbol = exchangeSymbol(canonical, 'binance');
    this.syncInFlight.set(canonical, true);
    let snap;
    try {
      const resp = await fetch(`${REST_BASE}/fapi/v1/depth?symbol=${symbol}&limit=1000`);
      snap = await resp.json();
    } finally {
      this.syncInFlight.set(canonical, false);
    }

    if (!snap.lastUpdateId) {
      this._backoffNextSync(canonical);
      this._lastSyncError = { canonical, code: snap.code, msg: snap.msg, at: Date.now() };
      logger.warn(
        `[binance] ${canonical} depth snapshot request failed (attempt ${this.syncFailureCount.get(canonical)}): ${JSON.stringify(snap)}`,
      );
      return;
    }
    this.syncFailureCount.set(canonical, 0);

    const lastUpdateId = snap.lastUpdateId;
    const book = this.books.get(canonical);
    book.applySnapshot(
      snap.bids.map(([p, q]) => [Number(p), Number(q)]),
      snap.asks.map(([p, q]) => [Number(p), Number(q)]),
    );

    const buffered = this.buffers.get(canonical).filter((e) => e.u >= lastUpdateId + 1);
    if (buffered.length === 0) {
      // Snapshot fetch succeeded but no buffered event covers it yet -
      // still need to wait for more depth events, not retry the REST
      // call immediately. Without this cooldown, a successful-but-not-
      // yet-aligned fetch was observed live to trigger another fetch on
      // the very next depth message (~100ms later), repeatedly burning
      // REST weight even though nothing was actually wrong.
      this.nextSyncAttemptAt.set(canonical, Date.now() + SYNC_BACKOFF_BASE_MS);
      return;
    }

    const first = buffered[0];
    if (!(first.U <= lastUpdateId + 1 && lastUpdateId + 1 <= first.u)) {
      this.buffers.set(canonical, [first]);
      this.nextSyncAttemptAt.set(canonical, Date.now() + SYNC_BACKOFF_BASE_MS);
      return;
    }

    for (const event of buffered) {
      this._applyUpdate(canonical, event);
    }
    this.synced.set(canonical, true);
    this.buffers.set(canonical, []);
  }

  _applyUpdate(canonical, data) {
    const book = this.books.get(canonical);
    book.applyDelta(
      data.b.map(([p, q]) => [Number(p), Number(q)]),
      data.a.map(([p, q]) => [Number(p), Number(q)]),
    );
    this.lastUpdateId.set(canonical, data.u);
    const { bids, asks } = book.topN(env.orderBookDepth);
    const event = {
      eventType: 'orderbook',
      exchange: this.name,
      symbol: canonical,
      marketType: 'perpetual',
      bids,
      asks,
      timestamp: data.E,
      sequence: data.u,
    };
    try {
      this.emit('orderbook', validateOrderBookEvent(event));
    } catch (err) {
      logger.error(`[binance] invalid orderbook event: ${err.message}`);
    }
  }
}
