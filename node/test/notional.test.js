import { test } from 'node:test';
import assert from 'node:assert/strict';
import { notionalUsd } from '../src/normalizer/notional.js';

test('notionalUsd multiplies price by quantity for linear contracts', () => {
  assert.equal(notionalUsd(100, 2), 200);
});

test('notionalUsd applies a contract multiplier when provided', () => {
  assert.equal(notionalUsd(100, 2, 0.01), 2);
});
