import { notionalUsd } from '../normalizer/notional.js';

/**
 * Aggregates the latest order book snapshot from each connected exchange
 * for one symbol into a single price-bucketed liquidity heatmap in USD
 * notional, so exchanges with different contract specs stay comparable
 * (never sum raw contract quantities across exchanges directly).
 */
export class LiquidityEngine {
  constructor({ symbol, bucketPct = 0.0005 } = {}) {
    this.symbol = symbol;
    this.bucketPct = bucketPct;
    this.latest = new Map(); // exchange -> { bids, asks, timestamp }
  }

  update({ exchange, bids, asks, timestamp }) {
    this.latest.set(exchange, { bids, asks, timestamp });
  }

  get connectedExchanges() {
    return [...this.latest.keys()];
  }

  midPrice() {
    const bestBids = [];
    const bestAsks = [];
    for (const { bids, asks } of this.latest.values()) {
      if (bids.length) bestBids.push(bids[0].price);
      if (asks.length) bestAsks.push(asks[0].price);
    }
    if (!bestBids.length || !bestAsks.length) return null;
    return (Math.max(...bestBids) + Math.min(...bestAsks)) / 2;
  }

  _bucketKey(price, mid) {
    const step = mid * this.bucketPct;
    if (step <= 0) return price;
    return Math.round(price / step) * step;
  }

  heatmap() {
    const mid = this.midPrice();
    if (mid === null) return [];
    const buckets = new Map();
    const add = (price, quantity, side) => {
      const key = this._bucketKey(price, mid);
      const entry = buckets.get(key) ?? { bid: 0, ask: 0 };
      entry[side] += notionalUsd(price, quantity);
      buckets.set(key, entry);
    };
    for (const { bids, asks } of this.latest.values()) {
      for (const level of bids) add(level.price, level.quantity, 'bid');
      for (const level of asks) add(level.price, level.quantity, 'ask');
    }
    return [...buckets.entries()]
      .map(([price, v]) => ({ price, bidNotionalUsd: v.bid, askNotionalUsd: v.ask }))
      .sort((a, b) => a.price - b.price);
  }

  concentrationAboveBelow(mid = this.midPrice()) {
    if (mid === null) return { above: 0, below: 0 };
    let above = 0;
    let below = 0;
    for (const bucket of this.heatmap()) {
      if (bucket.price >= mid) above += bucket.askNotionalUsd;
      else below += bucket.bidNotionalUsd;
    }
    return { above, below };
  }

  topWalls(n = 5) {
    return [...this.heatmap()]
      .sort((a, b) => b.bidNotionalUsd + b.askNotionalUsd - (a.bidNotionalUsd + a.askNotionalUsd))
      .slice(0, n);
  }

  /** -1 (all sell pressure) to +1 (all buy pressure), top-10-level notional. */
  orderbookImbalance() {
    let bidTotal = 0;
    let askTotal = 0;
    for (const { bids, asks } of this.latest.values()) {
      bidTotal += bids.slice(0, 10).reduce((sum, l) => sum + notionalUsd(l.price, l.quantity), 0);
      askTotal += asks.slice(0, 10).reduce((sum, l) => sum + notionalUsd(l.price, l.quantity), 0);
    }
    const total = bidTotal + askTotal;
    if (total === 0) return 0;
    return (bidTotal - askTotal) / total;
  }
}
