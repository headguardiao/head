import {
  NormalizedOrderBookSchema,
  NormalizedTradeSchema,
  NormalizedOpenInterestSchema,
  NormalizedFundingSchema,
  NormalizedLiquidationSchema,
} from './schema.js';

export function validateOrderBookEvent(event) {
  return NormalizedOrderBookSchema.parse(event);
}

export function validateTradeEvent(event) {
  return NormalizedTradeSchema.parse(event);
}

export function validateOpenInterestEvent(event) {
  return NormalizedOpenInterestSchema.parse(event);
}

export function validateFundingEvent(event) {
  return NormalizedFundingSchema.parse(event);
}

export function validateLiquidationEvent(event) {
  return NormalizedLiquidationSchema.parse(event);
}
