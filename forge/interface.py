from __future__ import annotations

from dataclasses import asdict

from config.settings import SIGNAL_MIN_CONFIDENCE
from forge.engine.glassnode_sentiment import compute_glassnode_sentiment
from forge.engine.onchain_engine import compute_onchain
from forge.engine.score_engine import SymbolMarketState
from forge.engine.sentiment_engine import compute_sentiment


class Heatmap:
    """Public interface consumed by the trading bot (PDF section 8):

        await heatmap.get_signal("BTCUSDT")
        await heatmap.get_sentiment("BTCUSDT")

    get_signal() returns liquidity_score, bias, concentration
    above/below, orderbook imbalance, OI change, funding, liquidation
    notional, top liquidity walls, confidence, and three sibling
    add-only blocks that never feed back into
    liquidity_score/bias/confidence: `glassnode` (on-chain via
    Glassnode, see glassnode_sentiment.py), `sentiment` (derivatives,
    see sentiment_engine.py - Camada C) and `onchain` (public on-chain
    via mempool.space/DefiLlama, see onchain_engine.py - Camada D).

    get_sentiment() is the standalone GET /sentiment/{symbol} - unlike
    get_signal(), it works for any symbol (not just ones this instance
    tracks order books for), since it's independent Binance-derivatives
    data; liq_side just stays unavailable if the symbol has no local
    state to reuse liquidations from.
    """

    def __init__(self, states: dict[str, SymbolMarketState]):
        self._states = states

    async def get_signal(self, symbol: str) -> dict:
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
            "glassnode": await compute_glassnode_sentiment(symbol),
            "sentiment": await compute_sentiment(symbol, states=self._states),
            "onchain": await compute_onchain(symbol),
        }

    async def get_sentiment(self, symbol: str) -> dict:
        return await compute_sentiment(symbol, states=self._states)
