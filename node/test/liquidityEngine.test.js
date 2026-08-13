import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LiquidityEngine } from '../src/engine/liquidityEngine.js';

function snap(bids, asks) {
  return {
    bids: bids.map(([price, quantity]) => ({ price, quantity })),
    asks: asks.map(([price, quantity]) => ({ price, quantity })),
    timestamp: Date.now(),
  };
}

test('midPrice is null with no data and defined once both sides exist', () => {
  const engine = new LiquidityEngine({ symbol: 'BTCUSDT' });
  assert.equal(engine.midPrice(), null);

  engine.update({ exchange: 'binance', ...snap([[100, 1]], [[101, 1]]) });
  assert.equal(engine.midPrice(), 100.5);
});

test('orderbookImbalance is positive when bid notional exceeds ask notional', () => {
  const engine = new LiquidityEngine({ symbol: 'BTCUSDT' });
  engine.update({ exchange: 'binance', ...snap([[100, 5]], [[101, 1]]) });
  const imbalance = engine.orderbookImbalance();
  assert.ok(imbalance > 0 && imbalance <= 1);
});

test('orderbookImbalance is 0 with no order book data', () => {
  const engine = new LiquidityEngine({ symbol: 'BTCUSDT' });
  assert.equal(engine.orderbookImbalance(), 0);
});

test('heatmap aggregates notional across exchanges at the same price bucket', () => {
  const engine = new LiquidityEngine({ symbol: 'BTCUSDT', bucketPct: 0 });
  engine.update({ exchange: 'binance', ...snap([[100, 1]], [[101, 1]]) });
  engine.update({ exchange: 'okx', ...snap([[100, 2]], [[101, 1]]) });

  const bucket100 = engine.heatmap().find((b) => b.price === 100);
  assert.equal(bucket100.bidNotionalUsd, 100 * 1 + 100 * 2);
});
