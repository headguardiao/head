from datetime import datetime, timezone

from forge.insights.engine import compute_insights
from forge.insights.models import MIN_SAMPLE_SIZE
from forge.ledger.models import MARKET_TYPE, VERIFICATION_STATUS_VERIFIED, StrategyTrade, Trade

USER_ID = "u1"


def _trade(i: int, *, net_pnl=1.0, hour: int = 0, minute: int = 0) -> Trade:
    ts = datetime(2026, 1, 1, hour, minute, tzinfo=timezone.utc).timestamp()
    return Trade(
        trade_id=f"trade-{i}",
        user_id=USER_ID,
        exchange="binance",
        external_id=f"ext-{i}",
        symbol="BTCUSDT",
        market_type=MARKET_TYPE,
        side="BUY",
        quantity=0.1,
        price=50000.0,
        fee=0.1,
        gross_pnl=net_pnl,
        net_pnl=net_pnl,
        funding=None,
        slippage=None,
        order_id=f"order-{i}",
        opened_at=ts,
        source="binance",
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )


def _strategy_trade(trade_id: str, origin: str = "OWN") -> StrategyTrade:
    return StrategyTrade(
        strategy_trade_id=f"st-{trade_id}", trade_id=trade_id, strategy_id="strat-1", origin=origin,
        classification="UNKNOWN",
    )


def test_no_trades_returns_insufficient_data():
    insights = compute_insights(USER_ID, [], {})
    assert len(insights) == 1
    assert insights[0].category == "insufficient_data"
    assert insights[0].sample_size == 0


def test_below_threshold_returns_insufficient_data():
    trades = [_trade(i, hour=i, net_pnl=1.0) for i in range(5)]
    links = {t.trade_id: _strategy_trade(t.trade_id) for t in trades}
    insights = compute_insights(USER_ID, trades, links)
    assert len(insights) == 1
    assert insights[0].category == "insufficient_data"
    assert insights[0].sample_size == 5


def test_performance_by_strategy_origin_above_threshold():
    # spread across distinct hours so the hour-of-day category doesn't
    # also cross MIN_SAMPLE_SIZE and show up in the result
    trades = [_trade(i, hour=i % 24, net_pnl=(10.0 if i % 3 else -5.0)) for i in range(MIN_SAMPLE_SIZE)]
    links = {t.trade_id: _strategy_trade(t.trade_id, origin="FINANCEX_ELITE") for t in trades}

    insights = compute_insights(USER_ID, trades, links)

    assert len(insights) == 1
    insight = insights[0]
    assert insight.category == "performance_por_estrategia"
    assert insight.evidence["origin"] == "FINANCEX_ELITE"
    expected_wins = sum(1 for i in range(MIN_SAMPLE_SIZE) if i % 3)
    assert insight.evidence["win_rate"] == expected_wins / MIN_SAMPLE_SIZE
    assert insight.sample_size == MIN_SAMPLE_SIZE


def test_consistency_by_hour_above_threshold():
    # all in the same hour, no strategy link -> origin category shouldn't fire
    trades = [_trade(i, hour=14, minute=i, net_pnl=(5.0 if i % 2 else -1.0)) for i in range(MIN_SAMPLE_SIZE)]

    insights = compute_insights(USER_ID, trades, {})

    assert len(insights) == 1
    insight = insights[0]
    assert insight.category == "consistencia_horario"
    assert insight.evidence["hour_utc"] == 14
    assert insight.sample_size == MIN_SAMPLE_SIZE


def test_trades_without_net_pnl_dont_count_toward_threshold():
    trades = [_trade(i, hour=14, minute=i, net_pnl=None) for i in range(MIN_SAMPLE_SIZE)]
    insights = compute_insights(USER_ID, trades, {})
    assert len(insights) == 1
    assert insights[0].category == "insufficient_data"


def test_trades_without_strategy_link_excluded_from_origin_category():
    trades = [_trade(i, hour=i % 24, net_pnl=1.0) for i in range(MIN_SAMPLE_SIZE)]
    # no strategy_trades links passed at all
    insights = compute_insights(USER_ID, trades, {})
    categories = {i.category for i in insights}
    assert "performance_por_estrategia" not in categories


def test_both_categories_can_appear_together():
    trades = [_trade(i, hour=9, minute=i, net_pnl=2.0) for i in range(MIN_SAMPLE_SIZE)]
    links = {t.trade_id: _strategy_trade(t.trade_id, origin="OWN") for t in trades}

    insights = compute_insights(USER_ID, trades, links)

    categories = {i.category for i in insights}
    assert categories == {"performance_por_estrategia", "consistencia_horario"}
