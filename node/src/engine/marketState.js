import { env } from '../config/env.js';
import { LiquidityEngine } from './liquidityEngine.js';
import { TradeBuffer } from './tradeBuffer.js';
import { computeScore } from './scoreEngine.js';

const OI_WINDOW_MS = 15 * 60 * 1000;
const LIQUIDATION_WINDOW_MS = 15 * 60 * 1000;
const HEATMAP_HISTORY_WINDOW_MS = 60 * 1000;
const HEATMAP_SNAPSHOT_INTERVAL_MS = 5000;

/** Per-symbol orchestration: ingests normalized events, exposes state for the API. */
export class MarketState {
  constructor(symbol) {
    this.symbol = symbol;
    this.liquidityEngine = new LiquidityEngine({ symbol });
    this.tradeBuffer = new TradeBuffer({ maxTrades: env.maxTradesPerSymbol });
    this.lastUpdatedAt = null;

    this.openInterestByExchange = new Map();
    this.oiHistory = []; // [{at, totalUsd}], trimmed to OI_WINDOW_MS
    this.fundingByExchange = new Map(); // exchange -> rate
    this.liquidations = []; // [{notionalUsd, timestamp}], trimmed to LIQUIDATION_WINDOW_MS
    this.heatmapHistory = []; // [{at, totals: Map(price -> bid+ask usd)}], trimmed to 60s, sampled every 5s
  }

  onOrderbook(event) {
    this.liquidityEngine.update(event);
    this.lastUpdatedAt = Date.now();
    this._recordHeatmapSnapshot();
  }

  onTrade(event) {
    this.tradeBuffer.push(event);
    this.lastUpdatedAt = Date.now();
  }

  onOpenInterest(event) {
    this.openInterestByExchange.set(event.exchange, event.valueUsd);
    const total = [...this.openInterestByExchange.values()].reduce((sum, v) => sum + v, 0);
    const now = Date.now();
    this.oiHistory.push({ at: now, totalUsd: total });
    this._trimByAge(this.oiHistory, OI_WINDOW_MS, 'at', now);
    this.lastUpdatedAt = now;
  }

  onFunding(event) {
    this.fundingByExchange.set(event.exchange, event.rate);
    this.lastUpdatedAt = Date.now();
  }

  onLiquidation(event) {
    const now = Date.now();
    // side kept (not just notionalUsd) so the add-only sentiment layer
    // can compute liq_side by reusing this instead of re-ingesting
    // liquidations from a second source.
    this.liquidations.push({
      notionalUsd: event.price * event.quantity,
      side: event.side,
      price: event.price,
      quantity: event.quantity,
      timestamp: event.timestamp,
    });
    this._trimByAge(this.liquidations, LIQUIDATION_WINDOW_MS, 'timestamp', now);
    this.lastUpdatedAt = now;
  }

  _recordHeatmapSnapshot() {
    const now = Date.now();
    const last = this.heatmapHistory[this.heatmapHistory.length - 1];
    if (last && now - last.at < HEATMAP_SNAPSHOT_INTERVAL_MS) return;
    const totals = new Map(this.liquidityEngine.heatmap().map((b) => [b.price, b.bidNotionalUsd + b.askNotionalUsd]));
    this.heatmapHistory.push({ at: now, totals });
    this._trimByAge(this.heatmapHistory, HEATMAP_HISTORY_WINDOW_MS, 'at', now);
  }

  _trimByAge(arr, windowMs, key, now) {
    let i = 0;
    while (i < arr.length && now - arr[i][key] > windowMs) i += 1;
    if (i > 0) arr.splice(0, i);
  }

  snapshot() {
    return {
      symbol: this.symbol,
      midPrice: this.liquidityEngine.midPrice(),
      connectedExchanges: this.liquidityEngine.connectedExchanges,
      orderbookImbalance: this.liquidityEngine.orderbookImbalance(),
      topLiquidityWalls: this.liquidityEngine.topWalls(),
      recentTradeCount: this.tradeBuffer.count,
      openInterestUsd: [...this.openInterestByExchange.values()].reduce((sum, v) => sum + v, 0) || null,
      recentLiquidationCount: this.liquidations.length,
      lastUpdatedAt: this.lastUpdatedAt,
    };
  }

  score() {
    return computeScore(this);
  }
}
