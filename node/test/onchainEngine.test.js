import { test } from 'node:test';
import assert from 'node:assert/strict';
import { COMPONENT_KEYS, computeOnchain, evaluateOnchainGate } from '../src/engine/onchainEngine.js';

function fakeClient({ dead = false } = {}) {
  const now = Date.now() / 1000;
  const fees = dead ? null : { fastestFee: 20 };
  const mempool = dead ? null : { count: 5000 };
  const hashrate = dead
    ? null
    : {
        hashrates: [
          { timestamp: now - 3 * 24 * 3600, avgHashrate: 5e20 },
          { timestamp: now, avgHashrate: 5.5e20 },
        ],
      };
  const tvl = dead
    ? null
    : [
        { date: now - 24 * 3600, tvl: 1_000_000_000 },
        { date: now, tvl: 1_050_000_000 },
      ];
  const stableCharts = dead
    ? null
    : [
        { date: now - 7 * 24 * 3600, totalCirculating: { peggedUSD: 100_000_000_000 } },
        { date: now, totalCirculating: { peggedUSD: 103_000_000_000 } },
      ];
  const stablePrices = dead
    ? null
    : [
        { symbol: 'USDT', price: 1.0005 },
        { symbol: 'USDC', price: 0.9998 },
      ];
  const gas = dead ? null : 25.0;

  return {
    async btcFeesRecommended() {
      return fees;
    },
    async btcMempool() {
      return mempool;
    },
    async btcHashrate() {
      return hashrate;
    },
    async historicalChainTvl() {
      return tvl;
    },
    async stablecoinChartsAll() {
      return stableCharts;
    },
    async stablecoinPrices() {
      return stablePrices;
    },
    async ethGasPriceGwei() {
      return gas;
    },
  };
}

test('dead sources degrade cleanly', async () => {
  const client = fakeClient({ dead: true });
  const result = await computeOnchain('BTCUSDT', client);

  assert.deepEqual(Object.keys(result.components).sort(), [...COMPONENT_KEYS].sort());
  assert.ok(Object.values(result.components).every((c) => c.avail === false));
  assert.equal(result.onchain_bias, 'NEUTRAL');
  assert.equal(result.onchain_confidence, 0);
  assert.equal(result.peg_stressed, false);
});

test('btc only uses global layer', async () => {
  const client = fakeClient();
  const result = await computeOnchain('BTCUSDT', client);

  assert.equal(result.chain_used, null);
  assert.equal(result.components.chain_tvl_1d.avail, false);
  assert.equal(result.components.eth_gas.avail, false);
  assert.equal(result.components.btc_fee.avail, true);
  assert.equal(result.components.btc_mempool.avail, true);
  assert.equal(result.components.btc_hashrate.avail, true);
  assert.ok(result.onchain_score >= -100 && result.onchain_score <= 100);
});

test('eth symbol gets chain and gas components', async () => {
  const client = fakeClient();
  const result = await computeOnchain('ETHUSDT', client);

  assert.equal(result.chain_used, 'Ethereum');
  assert.equal(result.components.chain_tvl_1d.avail, true);
  assert.equal(result.components.eth_gas.avail, true);
});

test('peg stress forces risk off', async () => {
  const client = fakeClient();
  client.stablecoinPrices = async () => [
    { symbol: 'USDT', price: 0.98 },
    { symbol: 'USDC', price: 1.0 },
  ];

  const result = await computeOnchain('BTCUSDT', client);

  assert.equal(result.peg_stressed, true);
  assert.equal(result.onchain_bias, 'RISK_OFF');
  assert.ok(result.notes.includes('stable peg stress'));
});

test('gate off by default always allows', () => {
  assert.equal(evaluateOnchainGate('RISK_OFF', true, 10, 'LONG', false), 'allow');
});

test('gate blocks long on peg stress', () => {
  assert.equal(evaluateOnchainGate('RISK_OFF', true, 10, 'LONG', true), 'block');
});

test('gate does not block short on peg stress', () => {
  assert.equal(evaluateOnchainGate('RISK_OFF', true, 10, 'SHORT', true), 'allow');
});

test('gate reduces on neutral with confidence', () => {
  assert.equal(evaluateOnchainGate('NEUTRAL', false, 60, 'LONG', true), 'reduce');
});
