import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canonicalFromExchange, exchangeSymbol, symbolsFor, trackedSymbols } from '../src/normalizer/symbols.js';

test('exchangeSymbol maps canonical symbols to each exchange format', () => {
  assert.equal(exchangeSymbol('BTCUSDT', 'binance'), 'BTCUSDT');
  assert.equal(exchangeSymbol('BTCUSDT', 'okx'), 'BTC-USDT-SWAP');
});

test('canonicalFromExchange round-trips for every symbol/exchange pair that exists', () => {
  // Not every tracked symbol has a live perpetual on both exchanges (e.g.
  // BONK/PEPE are OKX-only) - only round-trip pairs symbolsFor() confirms.
  for (const exchange of ['binance', 'okx']) {
    for (const canonical of symbolsFor(exchange)) {
      const exSymbol = exchangeSymbol(canonical, exchange);
      assert.equal(canonicalFromExchange(exchange, exSymbol), canonical);
    }
  }
});

test('symbolsFor only returns symbols with a live mapping on that exchange', () => {
  assert.ok(symbolsFor('okx').includes('BONKUSDT'));
  assert.ok(!symbolsFor('binance').includes('BONKUSDT'));
  assert.equal(trackedSymbols().length, symbolsFor('binance').length + symbolsFor('okx').length - intersectionCount());
});

function intersectionCount() {
  const b = new Set(symbolsFor('binance'));
  return symbolsFor('okx').filter((s) => b.has(s)).length;
}

test('canonicalFromExchange returns null for unknown symbols', () => {
  assert.equal(canonicalFromExchange('binance', 'DOESNOTEXIST'), null);
});

test('exchangeSymbol throws for unknown canonical/exchange pairs', () => {
  assert.throws(() => exchangeSymbol('DOESNOTEXIST', 'binance'));
});
