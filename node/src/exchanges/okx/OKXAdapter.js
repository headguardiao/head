import { ExchangeAdapter } from '../base/ExchangeAdapter.js';
import { LocalOrderBook } from '../../engine/localOrderBook.js';
import { canonicalFromExchange, exchangeSymbol, okxContractValue } from '../../normalizer/symbols.js';
import { notionalUsd } from '../../normalizer/notional.js';
import { validateOrderBookEvent, validateTradeEvent } from '../../normalizer/validate.js';
import { env } from '../../config/env.js';
import { logger } from '../../config/logger.js';

const WS_URL = 'wss://ws.okx.com:8443/ws/v5/public';
// OKX's docs cap a single subscribe message's arg list well under its
// message-size limit; chunking keeps each `subscribe` op small regardless
// of how many symbols this adapter tracks.
const SUBSCRIBE_CHUNK_SIZE = 40;

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

export class OKXAdapter extends ExchangeAdapter {
  constructor({ symbols }) {
    super({ name: 'okx', symbols });
    this.books = new Map(symbols.map((s) => [s, new LocalOrderBook({ maxLevels: env.orderBookDepth })]));
  }

  getWsUrl() {
    return WS_URL;
  }

  getSubscribeMessages() {
    const args = this.symbols.flatMap((s) => {
      const instId = exchangeSymbol(s, 'okx');
      return [
        { channel: 'books', instId },
        { channel: 'trades', instId },
      ];
    });
    return chunk(args, SUBSCRIBE_CHUNK_SIZE).map((batch) => ({ op: 'subscribe', args: batch }));
  }

  // OKX's public gateway expects an application-level text "ping", not a
  // WebSocket protocol ping frame.
  sendHeartbeat(ws) {
    ws.send('ping');
  }

  handleMessage(raw) {
    const text = raw.toString();
    if (text === 'pong') return;
    const msg = JSON.parse(text);
    const arg = msg.arg ?? {};
    if (arg.channel === 'books') this._handleBook(arg.instId, msg);
    else if (arg.channel === 'trades') this._handleTrades(arg.instId, msg);
  }

  _handleBook(instId, msg) {
    const canonical = canonicalFromExchange('okx', instId);
    if (!canonical) return;
    const ctVal = okxContractValue(canonical);
    const book = this.books.get(canonical);
    for (const entry of msg.data ?? []) {
      // OKX quotes size in contracts, not base-asset units - convert here
      // so every downstream consumer (LocalOrderBook, LiquidityEngine,
      // notionalUsd) can treat quantity as coin-denominated uniformly
      // across exchanges. See okxContractValue() for why this matters.
      const bids = entry.bids.map(([p, q]) => [Number(p), Number(q) * ctVal]);
      const asks = entry.asks.map(([p, q]) => [Number(p), Number(q) * ctVal]);
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
        logger.error(`[okx] invalid orderbook event: ${err.message}`);
      }
    }
  }

  _handleTrades(instId, msg) {
    const canonical = canonicalFromExchange('okx', instId);
    if (!canonical) return;
    const ctVal = okxContractValue(canonical);
    for (const t of msg.data ?? []) {
      const price = Number(t.px);
      const quantity = Number(t.sz) * ctVal;
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
        logger.error(`[okx] invalid trade event: ${err.message}`);
      }
    }
  }
}
