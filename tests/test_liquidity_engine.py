from forge.engine.liquidity_engine import LiquidityEngine
from forge.models import OrderBookSnapshot, PriceLevel


def _snap(exchange, bids, asks):
    return OrderBookSnapshot(
        exchange=exchange,
        symbol="BTCUSDT",
        timestamp=0.0,
        bids=[PriceLevel(p, q) for p, q in bids],
        asks=[PriceLevel(p, q) for p, q in asks],
    )


def test_mid_price_and_imbalance():
    engine = LiquidityEngine("BTCUSDT", bucket_pct=0.001)
    engine.update(_snap("binance", [(100.0, 1.0)], [(100.2, 1.0)]))
    engine.update(_snap("okx", [(99.9, 2.0)], [(100.3, 0.5)]))

    mid = engine.mid_price()
    assert 99.9 < mid < 100.3

    imbalance = engine.orderbook_imbalance()
    assert -1.0 <= imbalance <= 1.0
    assert imbalance > 0  # more bid notional than ask notional in this fixture


def test_heatmap_aggregates_across_exchanges():
    engine = LiquidityEngine("BTCUSDT", bucket_pct=0.0)
    engine.update(_snap("binance", [(100.0, 1.0)], [(101.0, 1.0)]))
    engine.update(_snap("okx", [(100.0, 2.0)], [(101.0, 1.0)]))

    hm = {b.price: b for b in engine.heatmap()}
    assert hm[100.0].bid_notional_usd == 100.0 * 1.0 + 100.0 * 2.0
    assert hm[101.0].ask_notional_usd == 101.0 * 1.0 + 101.0 * 1.0


def test_no_data_returns_empty_heatmap_and_none_mid():
    engine = LiquidityEngine("BTCUSDT")
    assert engine.mid_price() is None
    assert engine.heatmap() == []
    assert engine.orderbook_imbalance() == 0.0
