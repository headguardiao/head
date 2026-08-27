import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MarketState } from '../src/engine/marketState.js';
import { COMPONENT_KEYS, computeSentiment, evaluateSentimentGate } from '../src/engine/sentimentEngine.js';

function fakeClient({ dead = false } = {}) {
  const nowMs = Date.now();
  const fundingHistory = dead
    ? null
    : [
        ...Array.from({ length: 21 }, (_, i) => ({
          fundingTime: nowMs - (20 - i) * 8 * 3600 * 1000,
          fundingRate: String(0.0001 * (i % 2 ? 1 : -1)),
        })),
        { fundingTime: nowMs, fundingRate: '0.001' },
      ];
  const premium = dead ? null : { markPrice: '101.0', indexPrice: '100.0' };
  const globalLs = dead ? null : [{ longShortRatio: '0.8' }];
  const topLs = dead ? null : [{ longShortRatio: '2.5' }];
  const taker = dead ? null : { '15m': [{ buySellRatio: '1.2' }], '1h': [{ buySellRatio: '1.0' }] };
  const oiHist = dead ? null : [{ sumOpenInterestValue: '1000000' }, { sumOpenInterestValue: '1100000' }];
  const klines = dead ? null : [[0, '100', '0', '0', '0'], [0, '0', '0', '0', '105']];
  const fng = dead ? null : { data: [{ value: '20' }] };

  return {
    async fundingRateHistory() {
      return fundingHistory;
    },
    async premiumIndex() {
      return premium;
    },
    async globalLongShortRatio() {
      return globalLs;
    },
    async topLongShortPositionRatio() {
      return topLs;
    },
    async takerLongShortRatio(_symbol, period) {
      return dead ? null : taker[period];
    },
    async openInterestHist() {
      return oiHist;
    },
    async klines() {
      return klines;
    },
    async fearGreed() {
      return fng;
    },
  };
}

test('dead sources degrade cleanly', async () => {
  const client = fakeClient({ dead: true });
  const result = await computeSentiment('BTCUSDT', client);

  assert.deepEqual(Object.keys(result.components).sort(), [...COMPONENT_KEYS].sort());
  assert.ok(Object.values(result.components).every((c) => c.avail === false));
  assert.equal(result.sentiment_bias, 'NEUTRAL');
  assert.equal(result.sentiment_confidence, 0);
  assert.deepEqual(result.btc_anchor, { score: 0, bias: 'NEUTRAL' });
});

test('full sources compute a score', async () => {
  const client = fakeClient();
  const marketStates = new Map();
  const state = new MarketState('BTCUSDT');
  state.onLiquidation({ price: 100.0, quantity: 1.0, side: 'sell', timestamp: Date.now() });
  marketStates.set('BTCUSDT', state);

  const result = await computeSentiment('BTCUSDT', client, marketStates);

  assert.ok(Object.values(result.components).every((c) => c.avail === true));
  assert.equal(result.sentiment_confidence, 100);
  assert.ok(result.sentiment_score >= -100 && result.sentiment_score <= 100);
  assert.equal(result.components.whale_pos_ls.value, 2.5);
  assert.ok(result.notes.includes('whale crowded long'));
});

test('fng is tracked but never scored', async () => {
  const client = fakeClient();
  const baseline = await computeSentiment('BTCUSDT', client);

  const extremeClient = fakeClient();
  extremeClient.fearGreed = async () => ({ data: [{ value: '0' }] });
  const extreme = await computeSentiment('BTCUSDT', extremeClient);

  assert.equal(baseline.sentiment_score, extreme.sentiment_score);
  assert.equal(extreme.components.fng.avail, true);
  assert.equal(extreme.components.fng.value, 0);
});

test('liq_side reuses existing state liquidations', async () => {
  const client = fakeClient();
  const state = new MarketState('BTCUSDT');
  state.onLiquidation({ price: 100.0, quantity: 2.0, side: 'sell', timestamp: Date.now() });
  state.onLiquidation({ price: 100.0, quantity: 1.0, side: 'buy', timestamp: Date.now() });
  const marketStates = new Map([['BTCUSDT', state]]);

  const result = await computeSentiment('BTCUSDT', client, marketStates);

  const liq = result.components.liq_side;
  assert.equal(liq.avail, true);
  assert.ok(liq.value > 0);
  assert.ok(liq.score < 0);
});

test('alt symbol gets own and BTC anchor', async () => {
  const client = fakeClient();
  const result = await computeSentiment('ETHUSDT', client);

  assert.ok('btc_anchor' in result);
  assert.deepEqual(Object.keys(result.btc_anchor).sort(), ['bias', 'score']);
});

test('gate off by default always allows', () => {
  assert.equal(evaluateSentimentGate(-90, 10, 'LONG', false), 'allow');
});

test('gate blocks long on strong risk off', () => {
  assert.equal(evaluateSentimentGate(-30, 80, 'LONG', true), 'block');
});

test('gate blocks short on strong risk on', () => {
  assert.equal(evaluateSentimentGate(30, 80, 'SHORT', true), 'block');
});

test('gate reduces on neutral with confidence', () => {
  assert.equal(evaluateSentimentGate(0, 60, 'LONG', true), 'reduce');
});

test('gate allows when block threshold not met', () => {
  assert.equal(evaluateSentimentGate(-20, 80, 'LONG', true), 'allow');
});
