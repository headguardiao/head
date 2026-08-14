import { ExchangeAdapter } from '../base/ExchangeAdapter.js';
import { LocalOrderBook } from '../../engine/localOrderBook.js';
import { canonicalFromExchange, exchangeSymbol } from '../../normalizer/symbols.js';
import { notionalUsd } from '../../normalizer/notional.js';
import {
  validateOrderBookEvent,
  validateTradeEvent,
  validateOpenInterestEvent,
  validateFundingEvent,
} from '../../normalizer/validate.js';
import { env } from '../../config/env.js';
import { logger } from '../../config/logger.js';

const WS_URL = 'wss://ws.bitget.com/v2/ws/public';
const REST_BASE = 'https://api.bitget.com';
const PRODUCT_TYPE = 'USDT-FUTURES';
const REST_POLL_INTERVAL_MS = 30_000;
// Bitget's docs cap args per subscribe request; chunking keeps each op
// small regardless of how many symbols this adapter tracks.
const SUBSCRIBE_CHUNK_SIZE = 20;

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

export class BitgetAdapter extends ExchangeAdapter {
  constructor({ symbols }) {
    super({ name: 'bitget', symbols });
    this.books = new Map(symbols.map((s) => [s, new LocalOrderBook({ maxLevels: env.orderBookDepth })]));
    this.restPollIntervalMs = REST_POLL_INTERVAL_MS;
  }

  getWsUrl() {
    return WS_URL;
  }

  getSubscribeMessages() {
    const args = this.symbols.flatMap((s) => {
      const instId = exchangeSymbol(s, 'bitget');
      return [
        { instType: PRODUCT_TYPE, channel: 'books15', instId },
        { instType: PRODUCT_TYPE, channel: 'trade', instId },
      ];
    });
    return chunk(args, SUBSCRIBE_CHUNK_SIZE).map((batch) => ({ op: 'subscribe', args: batch }));
  }

  // Bitget's public gateway expects an application-level text "ping", not
  // a WebSocket protocol ping frame.
  sendHeartbeat(ws) {
    ws.send('ping');
  }

  handleMessage(raw) {
    const text = raw.toString();
    if (text === 'pong') return;
    const msg = JSON.parse(text);
    const arg = msg.arg ?? {};
    if (arg.channel === 'books15') this._handleBook(arg.instId, msg);
    else if (arg.channel === 'trade') this._handleTrades(arg.instId, msg);
  }

  _handleBook(instId, msg) {
    const canonical = canonicalFromExchange('bitget', instId);
    if (!canonical) return;
    const book = this.books.get(canonical);
    for (const entry of msg.data ?? []) {
      const bids = entry.bids.map(([p, q]) => [Number(p), Number(q)]);
      const asks = entry.asks.map(([p, q]) => [Number(p), Number(q)]);
      if (msg.action === 'snapshot') book.applySnapshot(bids, asks);
      else book.applyDelta(bids, asks);

      const { bids: bidsN, asks: asksN } = book.topN(env.orderBookDepth);
      const event = {
        eventType: 'orderbook',
        exchange: this.name,
        symbol: canonical,
        marketType: 'perpetual',
        bids: bidsN,
        asks: asksN,
        timestamp: Number(entry.ts),
        sequence: 0,
      };
      try {
        this.emit('orderbook', validateOrderBookEvent(event));
      } catch (err) {
        logger.error(`[bitget] invalid orderbook event: ${err.message}`);
      }
    }
  }

  _handleTrades(instId, msg) {
    const canonical = canonicalFromExchange('bitget', instId);
    if (!canonical) return;
    for (const t of msg.data ?? []) {
      const price = Number(t.price);
      const quantity = Number(t.size);
      const event = {
        eventType: 'trade',
        exchange: this.name,
        symbol: canonical,
        marketType: 'perpetual',
        price,
        quantity,
        notionalUsd: notionalUsd(price, quantity),
        side: t.side === 'buy' ? 'buy' : 'sell',
        timestamp: Number(t.ts),
        sequence: 0,
      };
      try {
        this.emit('trade', validateTradeEvent(event));
      } catch (err) {
        logger.error(`[bitget] invalid trade event: ${err.message}`);
      }
    }
  }

  async restPollOnce() {
    // The bulk tickers endpoint carries fundingRate, holdingAmount (open
    // interest in base-asset units) and markPrice together for every
    // symbol - one request instead of the 188 the Python prototype made
    // (two REST calls per symbol).
    try {
      const resp = await fetch(`${REST_BASE}/api/v2/mix/market/tickers?productType=${PRODUCT_TYPE}`);
      const payload = await resp.json();
      const now = Date.now();
      for (const row of payload.data ?? []) {
        const canonical = canonicalFromExchange('bitget', row.symbol);
        if (!canonical || !this.symbols.includes(canonical)) continue;

        if (row.fundingRate) {
          const fundingEvent = {
            eventType: 'funding',
            exchange: this.name,
            symbol: canonical,
            rate: Number(row.fundingRate),
            // Bitget's current-fund-rate endpoint doesn't expose the next
            // settlement time either (see README caveats); left at 0.
            nextFundingTime: 0,
            timestamp: now,
          };
          try {
            this.emit('funding', validateFundingEvent(fundingEvent));
          } catch (err) {
            logger.error(`[bitget] invalid funding event: ${err.message}`);
          }
        }

        const markPrice = Number(row.markPrice);
        if (row.holdingAmount && markPrice) {
          const oiEvent = {
            eventType: 'openInterest',
            exchange: this.name,
            symbol: canonical,
            valueUsd: Number(row.holdingAmount) * markPrice,
            timestamp: now,
          };
          try {
            this.emit('openInterest', validateOpenInterestEvent(oiEvent));
          } catch (err) {
            logger.error(`[bitget] invalid openInterest event: ${err.message}`);
          }
        }
      }
    } catch (err) {
      logger.error(`[bitget] tickers poll failed: ${err.message}`);
    }
  }
}
