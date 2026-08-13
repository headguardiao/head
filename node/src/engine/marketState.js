import { env } from '../config/env.js';
import { LiquidityEngine } from './liquidityEngine.js';
import { TradeBuffer } from './tradeBuffer.js';
import { computeProvisionalScore } from './scoreEngine.js';

/** Per-symbol orchestration: ingests normalized events, exposes state for the API. */
export class MarketState {
  constructor(symbol) {
    this.symbol = symbol;
    this.liquidityEngine = new LiquidityEngine({ symbol });
    this.tradeBuffer = new TradeBuffer({ maxTrades: env.maxTradesPerSymbol });
    this.lastUpdatedAt = null;
  }

  onOrderbook(event) {
    this.liquidityEngine.update(event);
    this.lastUpdatedAt = Date.now();
  }

  onTrade(event) {
    this.tradeBuffer.push(event);
    this.lastUpdatedAt = Date.now();
  }

  snapshot() {
    return {
      symbol: this.symbol,
      midPrice: this.liquidityEngine.midPrice(),
      connectedExchanges: this.liquidityEngine.connectedExchanges,
      orderbookImbalance: this.liquidityEngine.orderbookImbalance(),
      topLiquidityWalls: this.liquidityEngine.topWalls(),
      recentTradeCount: this.tradeBuffer.count,
      lastUpdatedAt: this.lastUpdatedAt,
    };
  }

  score() {
    return computeProvisionalScore(this.liquidityEngine, this.tradeBuffer);
  }
}
