/**
 * USD notional for an order-book level or trade. Binance/OKX quote
 * BTCUSDT/ETHUSDT perpetuals as linear USDT contracts with multiplier 1
 * (quantity already in base-asset units), so this is price*quantity by
 * default. Pass a multiplier for symbols/exchanges that quote in
 * contracts instead of coins - never sum raw contract quantities across
 * exchanges directly.
 */
export function notionalUsd(price, quantity, contractMultiplier = 1) {
  return price * quantity * contractMultiplier;
}
