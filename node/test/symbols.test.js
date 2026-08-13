import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canonicalFromExchange, exchangeSymbol, trackedSymbols } from '../src/normalizer/symbols.js';

test('exchangeSymbol maps canonical symbols to each exchange format', () => {
  assert.equal(exchangeSymbol('BTCUSDT', 'binance'), 'BTCUSDT');
  assert.equal(exchangeSymbol('BTCUSDT', 'okx'), 'BTC-USDT-SWAP');
});

test('canonicalFromExchange round-trips for every tracked symbol/exchange', () => {
  for (const canonical of trackedSymbols()) {
    for (const exchange of ['binance', 'okx']) {
      const exSymbol = exchangeSymbol(canonical, exchange);
      assert.equal(canonicalFromExchange(exchange, exSymbol), canonical);
    }
  }
});

test('canonicalFromExchange returns null for unknown symbols', () => {
  assert.equal(canonicalFromExchange('binance', 'DOESNOTEXIST'), null);
});

test('exchangeSymbol throws for unknown canonical/exchange pairs', () => {
  assert.throws(() => exchangeSymbol('DOESNOTEXIST', 'binance'));
});
