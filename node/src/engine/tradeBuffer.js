const DEFAULT_WINDOW_MS = 15 * 60 * 1000;

/**
 * Bounded rolling window of recent trades, capped both by count and by
 * age so memory can't grow without limit on a busy symbol.
 */
export class TradeBuffer {
  constructor({ maxTrades = 2000, windowMs = DEFAULT_WINDOW_MS } = {}) {
    this.maxTrades = maxTrades;
    this.windowMs = windowMs;
    this.trades = [];
  }

  push(trade) {
    this.trades.push(trade);
    if (this.trades.length > this.maxTrades) {
      this.trades.splice(0, this.trades.length - this.maxTrades);
    }
    this._trim();
  }

  _trim() {
    const cutoffMs = Date.now() - this.windowMs;
    let i = 0;
    while (i < this.trades.length && this.trades[i].timestamp < cutoffMs) i += 1;
    if (i > 0) this.trades.splice(0, i);
  }

  /** -1 (all sell flow) to +1 (all buy flow), a mini-CVD over the window. */
  flowImbalance() {
    this._trim();
    let buy = 0;
    let sell = 0;
    for (const t of this.trades) {
      if (t.side === 'buy') buy += t.notionalUsd;
      else sell += t.notionalUsd;
    }
    const total = buy + sell;
    if (total === 0) return 0;
    return (buy - sell) / total;
  }

  get count() {
    this._trim();
    return this.trades.length;
  }
}
