/**
 * Local bid/ask book built from a snapshot plus incremental deltas. A
 * delta level with quantity <= 0 removes that price level. Bounded to
 * roughly 2x maxLevels per side so a runaway feed can't grow memory
 * without limit.
 */
export class LocalOrderBook {
  constructor({ maxLevels = 50 } = {}) {
    this.maxLevels = maxLevels;
    this.bids = new Map(); // price -> quantity
    this.asks = new Map();
  }

  applySnapshot(bids, asks) {
    this.bids = new Map(bids.filter(([, q]) => q > 0));
    this.asks = new Map(asks.filter(([, q]) => q > 0));
    this._trim();
  }

  applyDelta(bids, asks) {
    for (const [price, quantity] of bids) {
      if (quantity <= 0) this.bids.delete(price);
      else this.bids.set(price, quantity);
    }
    for (const [price, quantity] of asks) {
      if (quantity <= 0) this.asks.delete(price);
      else this.asks.set(price, quantity);
    }
    this._trim();
  }

  _trim() {
    const cap = this.maxLevels * 2;
    if (this.bids.size > cap) {
      const kept = [...this.bids.entries()].sort((a, b) => b[0] - a[0]).slice(0, this.maxLevels);
      this.bids = new Map(kept);
    }
    if (this.asks.size > cap) {
      const kept = [...this.asks.entries()].sort((a, b) => a[0] - b[0]).slice(0, this.maxLevels);
      this.asks = new Map(kept);
    }
  }

  topN(n = this.maxLevels) {
    const bids = [...this.bids.entries()]
      .sort((a, b) => b[0] - a[0])
      .slice(0, n)
      .map(([price, quantity]) => ({ price, quantity }));
    const asks = [...this.asks.entries()]
      .sort((a, b) => a[0] - b[0])
      .slice(0, n)
      .map(([price, quantity]) => ({ price, quantity }));
    return { bids, asks };
  }

  bestBid() {
    return this.bids.size ? Math.max(...this.bids.keys()) : null;
  }

  bestAsk() {
    return this.asks.size ? Math.min(...this.asks.keys()) : null;
  }

  get isEmpty() {
    return this.bids.size === 0 || this.asks.size === 0;
  }
}
