import { ExchangeAdapter } from '../base/ExchangeAdapter.js';
import { LocalOrderBook } from '../../engine/localOrderBook.js';
import { canonicalFromExchange, exchangeSymbol, okxContractValue } from '../../normalizer/symbols.js';
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

const WS_URL = 'wss://ws.okx.com:8443/ws/v5/public';
const REST_BASE = 'https://www.okx.com';
const REST_POLL_INTERVAL_MS = 30_000;
// Funding-rate has no bulk endpoint (unlike open-interest with
// instType=SWAP), so it's one request per symbol - spaced out to avoid a
// rate-limit burst.
const FUNDING_POLL_SPACING_MS = 150;
// OKX's docs cap a single subscribe message's arg list well under its
// message-size limit; chunking keeps each `subscribe` op small regardless
// of how many symbols this adapter tracks.
const SUBSCRIBE_CHUNK_SIZE = 40;

function chunk(arr, size) {
  const out = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class OKXAdapter extends ExchangeAdapter {
  constructor({ symbols }) {
    super({ name: 'okx', symbols });
    this.books = new Map(symbols.map((s) => [s, new LocalOrderBook({ maxLevels: env.orderBookDepth })]));
    this.restPollIntervalMs = REST_POLL_INTERVAL_MS;
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
    const batches = chunk(args, SUBSCRIBE_CHUNK_SIZE).map((batch) => ({ op: 'subscribe', args: batch }));
    // One subscription covers every SWAP instrument's liquidations - not
    // per-symbol like books/trades.
    batches.push({ op: 'subscribe', args: [{ channel: 'liquidation-orders', instType: 'SWAP' }] });
    return batches;
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
    else if (arg.channel === 'liquidation-orders') this._handleLiquidations(msg);
  }

  _handleLiquidations(msg) {
    for (const item of msg.data ?? []) {
      const canonical = canonicalFromExchange('okx', item.instId);
      if (!canonical) continue;
      const ctVal = okxContractValue(canonical);
      for (const detail of item.details ?? []) {
        const event = {
          eventType: 'liquidation',
          exchange: this.name,
          symbol: canonical,
          price: Number(detail.bkPx),
          quantity: Number(detail.sz) * ctVal,
          side: detail.side === 'buy' ? 'buy' : 'sell',
          timestamp: Number(detail.ts),
        };
        try {
          this.emit('liquidation', validateLiquidationEvent(event));
        } catch (err) {
          logger.error(`[okx] invalid liquidation event: ${err.message}`);
        }
      }
    }
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

  async restPollOnce() {
    // open-interest accepts instType=SWAP without instId and returns
    // every SWAP instrument in one response - far cheaper than 94 calls.
    try {
      const resp = await fetch(`${REST_BASE}/api/v5/public/open-interest?instType=SWAP`);
      const payload = await resp.json();
      const now = Date.now();
      for (const row of payload.data ?? []) {
        const canonical = canonicalFromExchange('okx', row.instId);
        if (!canonical || !this.symbols.includes(canonical)) continue;
        const valueUsd = row.oiUsd ? Number(row.oiUsd) : Number(row.oiCcy || row.oi) * this._midPriceHint(canonical);
        if (!valueUsd) continue;
        const event = { eventType: 'openInterest', exchange: this.name, symbol: canonical, valueUsd, timestamp: now };
        try {
          this.emit('openInterest', validateOpenInterestEvent(event));
        } catch (err) {
          logger.error(`[okx] invalid openInterest event: ${err.message}`);
        }
      }
    } catch (err) {
      logger.error(`[okx] open interest poll failed: ${err.message}`);
    }

    // funding-rate has no bulk endpoint - poll per symbol, spaced out.
    for (const canonical of this.symbols) {
      const instId = exchangeSymbol(canonical, 'okx');
      try {
        const resp = await fetch(`${REST_BASE}/api/v5/public/funding-rate?instId=${instId}`);
        const payload = await resp.json();
        const row = payload.data?.[0];
        if (!row) continue;
        const event = {
          eventType: 'funding',
          exchange: this.name,
          symbol: canonical,
          rate: Number(row.fundingRate),
          nextFundingTime: Number(row.nextFundingTime),
          timestamp: Date.now(),
        };
        this.emit('funding', validateFundingEvent(event));
      } catch (err) {
        logger.error(`[okx] funding poll failed for ${instId}: ${err.message}`);
      }
      await sleep(FUNDING_POLL_SPACING_MS);
    }
  }

  _midPriceHint(canonical) {
    const book = this.books.get(canonical);
    if (!book) return 0;
    const bid = book.bestBid();
    const ask = book.bestAsk();
    if (!bid || !ask) return 0;
    return (bid + ask) / 2;
  }
}
