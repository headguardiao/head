import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LocalOrderBook } from '../src/engine/localOrderBook.js';

test('topN returns bids sorted descending and asks sorted ascending', () => {
  const book = new LocalOrderBook({ maxLevels: 10 });
  book.applySnapshot(
    [
      [100, 1],
      [102, 1],
      [101, 1],
    ],
    [
      [105, 1],
      [103, 1],
      [104, 1],
    ],
  );

  const { bids, asks } = book.topN(10);
  assert.deepEqual(
    bids.map((l) => l.price),
    [102, 101, 100],
  );
  assert.deepEqual(
    asks.map((l) => l.price),
    [103, 104, 105],
  );
});

test('applyDelta removes a level when quantity is zero', () => {
  const book = new LocalOrderBook({ maxLevels: 10 });
  book.applySnapshot([[100, 1]], [[101, 1]]);
  book.applyDelta([[100, 0]], []);
  assert.equal(book.bestBid(), null);
});

test('order book is trimmed to roughly maxLevels per side', () => {
  const book = new LocalOrderBook({ maxLevels: 5 });
  const bids = Array.from({ length: 50 }, (_, i) => [100 - i, 1]);
  book.applySnapshot(bids, []);
  assert.ok(book.bids.size <= 10);
});
