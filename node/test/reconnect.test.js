import { test } from 'node:test';
import assert from 'node:assert/strict';
import { WebSocketServer } from 'ws';
import { ExchangeAdapter } from '../src/exchanges/base/ExchangeAdapter.js';

function waitFor(predicate, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const interval = setInterval(() => {
      if (predicate()) {
        clearInterval(interval);
        resolve();
      } else if (Date.now() - start > timeoutMs) {
        clearInterval(interval);
        reject(new Error('timeout waiting for condition'));
      }
    }, 20);
  });
}

test('adapter reconnects automatically after the server closes the socket', async () => {
  const wss = new WebSocketServer({ port: 0 });
  const port = wss.address().port;
  let connections = 0;

  wss.on('connection', (ws) => {
    connections += 1;
    if (connections === 1) {
      ws.close();
    }
  });

  class TestAdapter extends ExchangeAdapter {
    getWsUrl() {
      return `ws://127.0.0.1:${port}`;
    }

    handleMessage() {
      // no messages expected in this test
    }
  }

  const adapter = new TestAdapter({ name: 'test', symbols: ['BTCUSDT'] });
  adapter.backoffMs = 50; // speed up the test instead of the production default

  adapter.start();
  try {
    await waitFor(() => connections >= 2, 3000);
    assert.ok(connections >= 2, 'adapter should have reconnected at least once');
  } finally {
    await adapter.stop();
    await new Promise((resolve) => wss.close(resolve));
  }
});
