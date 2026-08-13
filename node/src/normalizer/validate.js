import { NormalizedOrderBookSchema, NormalizedTradeSchema } from './schema.js';

export function validateOrderBookEvent(event) {
  return NormalizedOrderBookSchema.parse(event);
}

export function validateTradeEvent(event) {
  return NormalizedTradeSchema.parse(event);
}
