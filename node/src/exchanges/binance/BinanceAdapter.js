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
    this._trySync(canonical).catch((err) => {
      logger.error(`[binance] ${canonical} resync failed: ${err.message}`);
      this._backoffNextSync(canonical);
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
