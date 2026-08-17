from __future__ import annotations

from dataclasses import asdict

from config.settings import SIGNAL_MIN_CONFIDENCE
from forge.engine.score_engine import SymbolMarketState


class Heatmap:
    """Public interface consumed by the trading bot (PDF section 8):

        heatmap.get_signal("BTCUSDT")

    Returns liquidity_score, bias, concentration above/below, orderbook
    imbalance, OI change, funding, liquidation notional, top liquidity
    walls and confidence.
    """

    def __init__(self, states: dict[str, SymbolMarketState]):
        self._states = states

    def get_signal(self, symbol: str) -> dict:
        state = self._states.get(symbol)
        if state is None:
            raise KeyError(f"symbol not tracked: {symbol}")
        b = state.compute()
        return {
            "symbol": symbol,
            "liquidity_score": b.liquidity_score,
            "bias": b.bias,
            "concentration_above_usd": b.concentration_above_usd,
            "concentration_below_usd": b.concentration_below_usd,
            "orderbook_imbalance": b.orderbook_imbalance,
            "oi_change_pct": b.oi_change_pct,
            "funding_rate": b.funding_rate,
            "liquidation_notional_usd": b.liquidation_notional_usd,
            "top_liquidity_walls": [asdict(w) for w in b.top_walls],
            "confidence": b.confidence,
            "connected_exchanges": b.connected_exchanges,
            "signal_ready": b.confidence >= SIGNAL_MIN_CONFIDENCE,
            "min_confidence_required": SIGNAL_MIN_CONFIDENCE,
        }
