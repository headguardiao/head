import { ExchangeAdapter } from '../base/ExchangeAdapter.js';
import { LocalOrderBook } from '../../engine/localOrderBook.js';
import { canonicalFromExchange, exchangeSymbol } from '../../normalizer/symbols.js';
import { notionalUsd } from '../../normalizer/notional.js';
import { validateOrderBookEvent, validateTradeEvent } from '../../normalizer/validate.js';
import { env } from '../../config/env.js';
import { logger } from '../../config/logger.js';

const WS_URL = 'wss://ws.bitget.com/v2/ws/public';
const PRODUCT_TYPE = 'USDT-FUTURES';
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
}
