import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hasSequenceGap } from '../src/exchanges/binance/sequence.js';

test('no gap when pu matches the last applied update id', () => {
  assert.equal(hasSequenceGap({ pu: 42 }, 42), false);
});

test('gap detected when pu does not match the last applied update id', () => {
  assert.equal(hasSequenceGap({ pu: 43 }, 42), true);
});
