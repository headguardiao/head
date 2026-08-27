import { test } from 'node:test';
import assert from 'node:assert/strict';
import { GlassnodeClient } from '../src/engine/glassnodeClient.js';
import {
  COMPONENT_KEYS,
  computeGlassnodeSentiment,
  evaluateGlassnodeGate,
  scoreMvrv,
  scoreNupl,
  scoreSopr,
  scoreSthMvrv,
  scoreSthSopr,
} from '../src/engine/glassnodeSentiment.js';

test('scoreSopr direction and notes', () => {
  let notes = [];
  assert.ok(scoreSopr(1.25, notes) < 0); // profit taking / distribution -> risk off lean
  assert.ok(notes.includes('sopr: profit taking'));

  notes = [];
  assert.ok(scoreSopr(0.75, notes) > 0); // capitulation spend -> risk on lean (contrarian)
  assert.ok(notes.includes('sopr: capitulation spend'));
});

test('scoreSthSopr direction', () => {
  assert.ok(scoreSthSopr(1.25) < 0);
  assert.ok(scoreSthSopr(0.75) > 0);
});

test('scoreMvrv direction and notes', () => {
  let notes = [];
  assert.ok(scoreMvrv(0.5, notes) > 0); // undervalued -> risk on lean
  notes = [];
  assert.ok(scoreMvrv(3.5, notes) < 0); // overheated -> risk off lean
  assert.ok(notes.includes('mvrv: euphoria'));

  notes = [];
  scoreMvrv(0.5, notes);
  assert.ok(notes.includes('mvrv: fear'));
});

test('scoreSthMvrv direction', () => {
  assert.ok(scoreSthMvrv(0.5) > 0);
  assert.ok(scoreSthMvrv(2.0) < 0);
});

test('scoreNupl direction', () => {
  assert.ok(scoreNupl(0.1) > 0); // below the .25 center -> risk on lean
  assert.ok(scoreNupl(0.9) < 0); // well above it -> risk off lean
});

test('no api key degrades cleanly', async () => {
  const client = new GlassnodeClient({ apiKey: '' });
  const result = await computeGlassnodeSentiment('BTCUSDT', client);

  assert.equal(result.has_key, false);
  assert.deepEqual(Object.keys(result.components).sort(), [...COMPONENT_KEYS].sort());
  assert.ok(Object.values(result.components).every((c) => c.avail === false));
  assert.equal(result.glassnode_bias, 'NEUTRAL');
  assert.equal(result.glassnode_confidence, 0);
  assert.equal(result.profile, '30m');
});

test('unauthorized key degrades cleanly', async () => {
  const client = new GlassnodeClient({ apiKey: 'bad-key' });
  client.ensureKeyValid = async () => false;

  const result = await computeGlassnodeSentiment('BTCUSDT', client);

  assert.equal(result.has_key, true);
  assert.ok(Object.values(result.components).every((c) => c.avail === false));
  assert.ok(result.notes.includes('glassnode unauthorized'));
});

function makeFakeClientWithFullData() {
  const client = new GlassnodeClient({ apiKey: 'good-key' });
  client.ensureKeyValid = async () => true;

  const now = Math.floor(Date.now() / 1000);
  const singleValueByPath = {
    '/v1/metrics/indicators/sopr': 1.2,
    '/v1/metrics/indicators/sopr_less_155': 1.1,
    '/v1/metrics/market/mvrv': 0.8,
    '/v1/metrics/market/mvrv_less_155': 0.9,
    '/v1/metrics/indicators/net_unrealized_profit_loss': 0.2,
  };
  const deltaSeriesByPath = {
    '/v1/metrics/distribution/balance_exchanges': [1000.0, 900.0],
    '/v1/metrics/distribution/supply_stablecoins_sum': [100000.0, 105000.0],
  };

  client.getMetric = async (path, asset, interval = '1h') => {
    if (deltaSeriesByPath[path]) {
      const [start, end] = deltaSeriesByPath[path];
      return { points: [{ t: now - 86400, v: start }, { t: now, v: end }], interval, note: null };
    }
    if (path === '/v1/metrics/distribution/exchange_net_position_change') {
      const points = Array.from({ length: 7 }, (_, i) => ({ t: now - (7 - i) * 3600, v: -100.0 * (7 - i) }));
      return { points, interval, note: null };
    }
    const v = singleValueByPath[path];
    if (v === undefined) return { points: null, interval, note: 'glassnode metric not found' };
    return { points: [{ t: now - 86400, v }, { t: now, v }], interval, note: null };
  };

  return client;
}

test('full components available computes a weighted score', async () => {
  const client = makeFakeClientWithFullData();
  const result = await computeGlassnodeSentiment('BTCUSDT', client);

  assert.equal(result.has_key, true);
  assert.equal(result.asset_used, 'BTC');
  assert.equal(result.asset_direct, true);
  assert.equal(result.profile, '30m');
  assert.ok(Object.values(result.components).every((c) => c.avail === true));
  assert.equal(result.glassnode_confidence, 100);
  assert.ok(result.glassnode_score >= -100 && result.glassnode_score <= 100);
});

test('profile selection changes the weighting', async () => {
  const client = makeFakeClientWithFullData();
  const original = process.env.FORGE_SENTIMENT_PROFILE;
  try {
    delete process.env.FORGE_SENTIMENT_PROFILE;
    const result30m = await computeGlassnodeSentiment('BTCUSDT', client);

    process.env.FORGE_SENTIMENT_PROFILE = '2h';
    const result2h = await computeGlassnodeSentiment('BTCUSDT', client);

    assert.equal(result30m.profile, '30m');
    assert.equal(result2h.profile, '2h');
    assert.notEqual(result30m.glassnode_score, result2h.glassnode_score);
  } finally {
    if (original === undefined) delete process.env.FORGE_SENTIMENT_PROFILE;
    else process.env.FORGE_SENTIMENT_PROFILE = original;
  }
});

test('unknown profile falls back to 30m', async () => {
  const client = new GlassnodeClient({ apiKey: '' });
  const original = process.env.FORGE_SENTIMENT_PROFILE;
  try {
    process.env.FORGE_SENTIMENT_PROFILE = 'weekly';
    const result = await computeGlassnodeSentiment('BTCUSDT', client);
    assert.equal(result.profile, '30m');
  } finally {
    if (original === undefined) delete process.env.FORGE_SENTIMENT_PROFILE;
    else process.env.FORGE_SENTIMENT_PROFILE = original;
  }
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

test('closeTime excludes future points', async () => {
  const client = new GlassnodeClient({ apiKey: 'good-key' });
  client.ensureKeyValid = async () => true;
  const now = Math.floor(Date.now() / 1000);
  const cutoff = now - 3600;

  client.getMetric = async (path, asset, interval = '1h') => {
    if (path === '/v1/metrics/indicators/sopr') {
      const points = [{ t: cutoff - 60, v: 1.1 }, { t: now, v: 999.0 }];
      return { points, interval, note: null };
    }
    return { points: null, interval, note: 'glassnode metric not found' };
  };

  const result = await computeGlassnodeSentiment('BTCUSDT', client, cutoff);
  assert.equal(result.components.sopr.value, 1.1);
});

test('gate off by default always allows', () => {
  assert.equal(evaluateGlassnodeGate({}, -50, 100, 'LONG', false), 'allow');
});

test('gate blocks long on low score', () => {
  assert.equal(evaluateGlassnodeGate({}, -12, 100, 'LONG', true), 'block');
});

test('gate blocks long on profit/distribution combo', () => {
  const components = { sopr: { value: 1.1 }, sth_mvrv: { value: 1.3 } };
  assert.equal(evaluateGlassnodeGate(components, 0, 100, 'LONG', true), 'block');
});

test('gate blocks long on mvrv euphoria', () => {
  const components = { mvrv: { value: 2.5 } };
  assert.equal(evaluateGlassnodeGate(components, 0, 100, 'LONG', true), 'block');
});

test('gate blocks long on extreme negative netflow score', () => {
  const components = { exch_netflow: { score: -60 } };
  assert.equal(evaluateGlassnodeGate(components, 0, 100, 'LONG', true), 'block');
});

test('gate blocks short on high score', () => {
  assert.equal(evaluateGlassnodeGate({}, 28, 100, 'SHORT', true), 'block');
});

test('gate blocks short on sth_sopr and netflow combo', () => {
  const components = { sth_sopr: { value: 0.9 }, exch_netflow: { score: 60 } };
  assert.equal(evaluateGlassnodeGate(components, 0, 100, 'SHORT', true), 'block');
});

test('gate reduces on neutral with confidence', () => {
  assert.equal(evaluateGlassnodeGate({}, 0, 60, 'LONG', true), 'reduce');
});

test('gate allows when nothing triggers', () => {
  assert.equal(evaluateGlassnodeGate({}, 5, 20, 'LONG', true), 'allow');
});
