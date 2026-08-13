import time

from forge.engine.score_engine import SymbolMarketState
from forge.models import FundingRate, OpenInterest, OrderBookSnapshot, PriceLevel, Side, Trade


def test_score_is_bounded_and_confidence_reflects_exchange_count():
    state = SymbolMarketState("BTCUSDT", min_exchanges_for_full_confidence=4)

    state.on_orderbook(OrderBookSnapshot(
        exchange="binance", symbol="BTCUSDT", timestamp=time.time(),
        bids=[PriceLevel(100.0, 5.0)], asks=[PriceLevel(101.0, 1.0)],
    ))
    state.on_trade(Trade(
        exchange="binance", symbol="BTCUSDT", price=100.5, qty=1.0,
        side=Side.SELL, timestamp=time.time(),
    ))
    state.on_open_interest(OpenInterest(
        exchange="binance", symbol="BTCUSDT", value_usd=1_000_000, timestamp=time.time(),
    ))
    state.on_funding(FundingRate(
        exchange="binance", symbol="BTCUSDT", rate=0.0004, next_funding_time=0, timestamp=time.time(),
    ))

    breakdown = state.compute()

    assert 0 <= breakdown.liquidity_score <= 100
    assert breakdown.bias in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert breakdown.confidence == 25.0  # 1 of 4 expected exchanges connected


def test_more_connected_exchanges_raise_confidence():
    state = SymbolMarketState("BTCUSDT", min_exchanges_for_full_confidence=4)
    for exchange in ("binance", "okx", "bybit", "bitget"):
        state.on_orderbook(OrderBookSnapshot(
            exchange=exchange, symbol="BTCUSDT", timestamp=time.time(),
            bids=[PriceLevel(100.0, 1.0)], asks=[PriceLevel(101.0, 1.0)],
        ))
    breakdown = state.compute()
    assert breakdown.confidence == 100.0
    assert len(breakdown.connected_exchanges) == 4
