import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from '../src/api/server.js';
import { MarketState } from '../src/engine/marketState.js';

function startTestServer() {
  const marketStates = new Map([['BTCUSDT', new MarketState('BTCUSDT')]]);
  const adapters = [{ name: 'binance', connected: true, lastMessageAt: Date.now() }];
  const app = createServer({ marketStates, adapters, startedAt: Date.now() });
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ server, baseUrl: `http://127.0.0.1:${port}` });
    });
  });
}

test('GET /health reports process and exchange connection status', async () => {
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/health`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.status, 'ok');
    assert.equal(body.exchanges.binance.connected, true);
  } finally {
    server.close();
  }
});

test('GET /api/market/:symbol returns the normalized snapshot for a tracked symbol', async () => {
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/api/market/BTCUSDT`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.symbol, 'BTCUSDT');
    assert.equal(body.midPrice, null);
  } finally {
    server.close();
  }
});

test('GET /api/market/:symbol 404s for an untracked symbol', async () => {
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/api/market/DOGEUSDT`);
    assert.equal(res.status, 404);
  } finally {
    server.close();
  }
});

test('GET /api/score/:symbol reports not enough data before any order book arrives', async () => {
  const { server, baseUrl } = await startTestServer();
  try {
    const res = await fetch(`${baseUrl}/api/score/BTCUSDT`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.hasEnoughData, false);
  } finally {
    server.close();
  }
});
