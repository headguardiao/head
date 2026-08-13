import { z } from 'zod';

export const Side = z.enum(['buy', 'sell']);
export const MarketType = z.enum(['perpetual']);

export const PriceLevelSchema = z.object({
  price: z.number().positive(),
  quantity: z.number().nonnegative(),
});

export const NormalizedOrderBookSchema = z.object({
  eventType: z.literal('orderbook'),
  exchange: z.string().min(1),
  symbol: z.string().min(1),
  marketType: MarketType,
  bids: z.array(PriceLevelSchema),
  asks: z.array(PriceLevelSchema),
  timestamp: z.number().int().positive(),
  sequence: z.number().int().nonnegative(),
});

export const NormalizedTradeSchema = z.object({
  eventType: z.literal('trade'),
  exchange: z.string().min(1),
  symbol: z.string().min(1),
  marketType: MarketType,
  price: z.number().positive(),
  quantity: z.number().positive(),
  notionalUsd: z.number().nonnegative(),
  side: Side,
  timestamp: z.number().int().positive(),
  sequence: z.number().int().nonnegative(),
});

export const NormalizedEventSchema = z.union([NormalizedOrderBookSchema, NormalizedTradeSchema]);
