import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canonicalFromExchange, exchangeSymbol, symbolsFor, trackedSymbols } from '../src/normalizer/symbols.js';

test('exchangeSymbol maps canonical symbols to each exchange format', () => {
  assert.equal(exchangeSymbol('BTCUSDT', 'binance'), 'BTCUSDT');
  assert.equal(exchangeSymbol('BTCUSDT', 'okx'), 'BTC-USDT-SWAP');
});

test('canonicalFromExchange round-trips for every symbol/exchange pair that exists', () => {
  // Not every tracked symbol has a live perpetual on every exchange (e.g.
  // BONK is OKX-only) - only round-trip pairs symbolsFor() confirms.
  for (const exchange of ['binance', 'okx', 'bybit', 'bitget']) {
    for (const canonical of symbolsFor(exchange)) {
      const exSymbol = exchangeSymbol(canonical, exchange);
      assert.equal(canonicalFromExchange(exchange, exSymbol), canonical);
    }
  }
});

test('symbolsFor only returns symbols with a live mapping on that exchange', () => {
  assert.ok(symbolsFor('okx').includes('BONKUSDT'));
  assert.ok(!symbolsFor('binance').includes('BONKUSDT'));
  assert.ok(!symbolsFor('bybit').includes('BONKUSDT'));
});

test('every tracked symbol has a mapping on at least one exchange', () => {
  const covered = new Set([
    ...symbolsFor('binance'),
    ...symbolsFor('okx'),
    ...symbolsFor('bybit'),
    ...symbolsFor('bitget'),
  ]);
  for (const canonical of trackedSymbols()) {
    assert.ok(covered.has(canonical), `${canonical} has no exchange mapping`);
  }
});

test('canonicalFromExchange returns null for unknown symbols', () => {
  assert.equal(canonicalFromExchange('binance', 'DOESNOTEXIST'), null);
});

test('exchangeSymbol throws for unknown canonical/exchange pairs', () => {
  assert.throws(() => exchangeSymbol('DOESNOTEXIST', 'binance'));
});
