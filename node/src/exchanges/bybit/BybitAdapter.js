import { ExchangeAdapter } from '../base/ExchangeAdapter.js';
import { LocalOrderBook } from '../../engine/localOrderBook.js';
import { canonicalFromExchange, exchangeSymbol } from '../../normalizer/symbols.js';
import { notionalUsd } from '../../normalizer/notional.js';
import {
  validateOrderBookEvent,
  validateTradeEvent,
  validateOpenInterestEvent,
  validateFundingEvent,
  validateLiquidationEvent,
} from '../../normalizer/validate.js';
import { env } from '../../config/env.js';
import { logger } from '../../config/logger.js';

const WS_URL = 'wss://stream.bybit.com/v5/public/linear';
const REST_BASE = 'https://api.bybit.com';
const DEPTH_LEVELS = 50;
const REST_POLL_INTERVAL_MS = 30_000;
// Bybit's docs cap args per subscribe request; chunking keeps each op
// small regardless of how many symbols this adapter tracks.
const SUBSCRIBE_CHUNK_SIZE = 10;

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

export class BybitAdapter extends ExchangeAdapter {
  constructor({ symbols }) {
    super({ name: 'bybit', symbols });
    this.books = new Map(symbols.map((s) => [s, new LocalOrderBook({ maxLevels: env.orderBookDepth })]));
    this.restPollIntervalMs = REST_POLL_INTERVAL_MS;
  }

  getWsUrl() {
    return WS_URL;
  }

  getSubscribeMessages() {
    const topics = this.symbols.flatMap((s) => {
      const sym = exchangeSymbol(s, 'bybit');
      // NOTE: Bybit deprecated the per-liquidation "liquidation.<symbol>"
      // topic in favor of "allLiquidation.<symbol>" - subscribing to the
      // old name doesn't error, it just silently stops the server from
      // pushing *any* data on the whole connection (found via live testing
      // in the Python prototype, see forge/adapters/bybit.py).
      return [`orderbook.${DEPTH_LEVELS}.${sym}`, `publicTrade.${sym}`, `allLiquidation.${sym}`];
    });
    return chunk(topics, SUBSCRIBE_CHUNK_SIZE).map((batch) => ({ op: 'subscribe', args: batch }));
  }

  // Bybit's public gateway expects an application-level {"op":"ping"}
  // message, not a WebSocket protocol ping frame.
  sendHeartbeat(ws) {
    ws.send(JSON.stringify({ op: 'ping' }));
  }

  handleMessage(raw) {
    const msg = JSON.parse(raw.toString());
    const topic = msg.topic ?? '';
    if (topic.startsWith('orderbook.')) this._handleBook(msg);
    else if (topic.startsWith('publicTrade.')) this._handleTrades(msg);
    else if (topic.startsWith('allLiquidation.')) this._handleLiquidations(msg);
  }

  _handleBook(msg) {
    const data = msg.data ?? {};
    const canonical = canonicalFromExchange('bybit', data.s);
    if (!canonical) return;
    const book = this.books.get(canonical);
    const bids = (data.b ?? []).map(([p, q]) => [Number(p), Number(q)]);
    const asks = (data.a ?? []).map(([p, q]) => [Number(p), Number(q)]);
    if (msg.type === 'snapshot') book.applySnapshot(bids, asks);
    else book.applyDelta(bids, asks);

    const { bids: bidsN, asks: asksN } = book.topN(env.orderBookDepth);
    const event = {
      eventType: 'orderbook',
      exchange: this.name,
      symbol: canonical,
      marketType: 'perpetual',
      bids: bidsN,
      asks: asksN,
      timestamp: msg.ts,
      sequence: data.u ?? 0,
    };
    try {
      this.emit('orderbook', validateOrderBookEvent(event));
    } catch (err) {
      logger.error(`[bybit] invalid orderbook event: ${err.message}`);
    }
  }

  _handleTrades(msg) {
    for (const t of msg.data ?? []) {
      const canonical = canonicalFromExchange('bybit', t.s);
      if (!canonical) continue;
      const price = Number(t.p);
      const quantity = Number(t.v);
      const event = {
        eventType: 'trade',
        exchange: this.name,
        symbol: canonical,
        marketType: 'perpetual',
        price,
        quantity,
        notionalUsd: notionalUsd(price, quantity),
        side: t.S === 'Buy' ? 'buy' : 'sell',
        timestamp: Number(t.T),
        sequence: 0,
      };
      try {
        this.emit('trade', validateTradeEvent(event));
      } catch (err) {
        logger.error(`[bybit] invalid trade event: ${err.message}`);
      }
    }
  }

  // allLiquidation.<symbol> pushes a list of entries: s, S, v, p, T.
  _handleLiquidations(msg) {
    for (const entry of msg.data ?? []) {
      const canonical = canonicalFromExchange('bybit', entry.s);
      if (!canonical) continue;
      const event = {
        eventType: 'liquidation',
        exchange: this.name,
        symbol: canonical,
        price: Number(entry.p),
        quantity: Number(entry.v),
        side: entry.S === 'Buy' ? 'buy' : 'sell',
        timestamp: Number(entry.T),
      };
      try {
        this.emit('liquidation', validateLiquidationEvent(event));
      } catch (err) {
        logger.error(`[bybit] invalid liquidation event: ${err.message}`);
      }
    }
  }

  async restPollOnce() {
    // tickers without a `symbol` param returns every linear instrument in
    // one response, including fundingRate and openInterestValue directly -
    // one request covers all 94 symbols instead of 94 separate calls.
    try {
      const resp = await fetch(`${REST_BASE}/v5/market/tickers?category=linear`);
      const payload = await resp.json();
      const rows = payload.result?.list ?? [];
      const now = Date.now();
      for (const row of rows) {
        const canonical = canonicalFromExchange('bybit', row.symbol);
        if (!canonical || !this.symbols.includes(canonical)) continue;

        if (row.fundingRate) {
          const fundingEvent = {
            eventType: 'funding',
            exchange: this.name,
            symbol: canonical,
            rate: Number(row.fundingRate),
            nextFundingTime: Number(row.nextFundingTime ?? 0),
            timestamp: now,
          };
          try {
            this.emit('funding', validateFundingEvent(fundingEvent));
          } catch (err) {
            logger.error(`[bybit] invalid funding event: ${err.message}`);
          }
        }

        if (row.openInterestValue) {
          const oiEvent = {
            eventType: 'openInterest',
            exchange: this.name,
            symbol: canonical,
            valueUsd: Number(row.openInterestValue),
            timestamp: now,
          };
          try {
            this.emit('openInterest', validateOpenInterestEvent(oiEvent));
          } catch (err) {
            logger.error(`[bybit] invalid openInterest event: ${err.message}`);
          }
        }
      }
    } catch (err) {
      logger.error(`[bybit] tickers poll failed: ${err.message}`);
    }
  }
}
