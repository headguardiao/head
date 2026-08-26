import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GlassnodeClient } from '../src/engine/glassnodeClient.js';
import {
  COMPONENT_KEYS,
  computeGlassnodeSentiment,
  scoreSopr,
  scoreMvrv,
  scoreNupl,
} from '../src/engine/glassnodeSentiment.js';

test('scoreSopr direction', () => {
  assert.ok(scoreSopr(1.25) > 0); // profit realized without panic -> risk on lean
  assert.ok(scoreSopr(0.75) < 0); // realized losses -> risk off lean
  assert.equal(scoreSopr(1.0), 0);
});

test('scoreMvrv direction', () => {
  assert.ok(scoreMvrv(0.5) > 0); // undervalued -> risk on lean
  assert.ok(scoreMvrv(3.5) < 0); // overheated -> risk off lean
});

test('scoreNupl direction', () => {
  assert.ok(scoreNupl(0.1) > 0); // capitulation/fear zone -> risk on lean
  assert.ok(scoreNupl(0.9) < 0); // euphoria/greed -> risk off lean
});

test('no api key degrades cleanly', async () => {
  const client = new GlassnodeClient({ apiKey: '' });
  const result = await computeGlassnodeSentiment('BTCUSDT', client);

  assert.equal(result.has_key, false);
  assert.deepEqual(Object.keys(result.components).sort(), [...COMPONENT_KEYS].sort());
  assert.ok(Object.values(result.components).every((c) => c.avail === false));
  assert.equal(result.glassnode_bias, 'NEUTRAL');
  assert.equal(result.glassnode_confidence, 0);
});

test('unauthorized key degrades cleanly', async () => {
  const client = new GlassnodeClient({ apiKey: 'bad-key' });
  client.ensureKeyValid = async () => false;

  const result = await computeGlassnodeSentiment('BTCUSDT', client);

  assert.equal(result.has_key, true);
  assert.ok(Object.values(result.components).every((c) => c.avail === false));
  assert.ok(result.notes.includes('glassnode unauthorized'));
});

test('full components available computes a score', async () => {
  const client = new GlassnodeClient({ apiKey: 'good-key' });
  client.ensureKeyValid = async () => true;

  const now = Math.floor(Date.now() / 1000);
  const singleValueByPath = {
    '/v1/metrics/indicators/sopr': 1.2,
    '/v1/metrics/indicators/sopr_less_155': 1.1,
    '/v1/metrics/market/mvrv': 0.8,
    '/v1/metrics/market/mvrv_less_155': 0.9,
    '/v1/metrics/indicators/net_unrealized_profit_loss': 0.2,
    '/v1/metrics/distribution/exchange_net_position_change': -500.0,
  };
  const deltaSeriesByPath = {
    '/v1/metrics/distribution/balance_exchanges': [1000.0, 900.0],
    '/v1/metrics/distribution/supply_stablecoins_sum': [100000.0, 105000.0],
  };

  client.getMetric = async (path, asset, interval = '1h') => {
    if (deltaSeriesByPath[path]) {
      const [start, end] = deltaSeriesByPath[path];
      const points = [{ t: now - 86400, v: start }, { t: now, v: end }];
      return { points, interval, note: null };
    }
    const v = singleValueByPath[path];
    if (v === undefined) return { points: null, interval, note: 'glassnode metric not found' };
    const points = [{ t: now - 86400, v }, { t: now, v }];
    return { points, interval, note: null };
  };

  const result = await computeGlassnodeSentiment('BTCUSDT', client);

  assert.equal(result.has_key, true);
  assert.equal(result.asset_used, 'BTC');
  assert.equal(result.asset_direct, true);
  assert.ok(Object.values(result.components).every((c) => c.avail === true));
  assert.equal(result.glassnode_confidence, 100);
  assert.ok(result.glassnode_score >= -100 && result.glassnode_score <= 100);
  assert.ok(['RISK_ON', 'RISK_OFF', 'NEUTRAL'].includes(result.glassnode_bias));
});

test('alt symbol anchors on BTC', async () => {
  const client = new GlassnodeClient({ apiKey: 'good-key' });
  client.ensureKeyValid = async () => true;
  client.getMetric = async (path, asset, interval = '1h') => {
    assert.equal(asset, 'BTC'); // alts must never call Glassnode with their own ticker
    return { points: null, interval, note: 'glassnode metric not found' };
  };

  const result = await computeGlassnodeSentiment('SOLUSDT', client);

  assert.equal(result.asset_used, 'BTC');
  assert.equal(result.asset_direct, false);
});
