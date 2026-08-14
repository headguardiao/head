import pytest

from forge.insights.db import InsightsRepo
from forge.insights.db import init_db as init_insights_db
from forge.insights.models import MIN_SAMPLE_SIZE
from forge.insights.service import InsightsService
from forge.ledger.db import StrategyTradesRepo, TradesRepo
from forge.ledger.db import init_db as init_ledger_db
from forge.ledger.models import MARKET_TYPE, VERIFICATION_STATUS_VERIFIED, Trade

USER_ID = "u1"


def _trade(i: int) -> Trade:
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
        gross_pnl=1.0,
        net_pnl=1.0,
        funding=None,
        slippage=None,
        order_id=f"order-{i}",
        opened_at=1700000000.0 + i * 3600,  # spread across distinct hours
        source="binance",
        verification_status=VERIFICATION_STATUS_VERIFIED,
    )


@pytest.fixture
async def rig(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_ledger_db(db_path)
    await init_insights_db(db_path)

    trades_repo = TradesRepo(db_path)
    strategy_trades_repo = StrategyTradesRepo(db_path)
    service = InsightsService(InsightsRepo(db_path), trades_repo, strategy_trades_repo)
    return trades_repo, strategy_trades_repo, service


async def test_generate_persists_and_returns_insights(rig):
    trades_repo, strategy_trades_repo, service = rig
    for i in range(MIN_SAMPLE_SIZE):
        trade = _trade(i)
        await trades_repo.insert_if_new(trade)
        await strategy_trades_repo.create(
            trade_id=trade.trade_id, strategy_id="strat-1", origin="FINANCEX_NORMAL", classification="UNKNOWN"
        )

    generated = await service.generate(USER_ID)
    assert any(i.category == "performance_por_estrategia" for i in generated)

    history = await service.list_insights(USER_ID)
    assert len(history) == len(generated)


async def test_generate_with_no_trades_returns_insufficient_data(rig):
    _, _, service = rig
    generated = await service.generate("brand-new-user")
    assert len(generated) == 1
    assert generated[0].category == "insufficient_data"


async def test_list_insights_scoped_to_user(rig):
    trades_repo, strategy_trades_repo, service = rig
    for i in range(MIN_SAMPLE_SIZE):
        trade = _trade(i)
        await trades_repo.insert_if_new(trade)
    await service.generate(USER_ID)

    assert len(await service.list_insights(USER_ID)) >= 1
    assert await service.list_insights("someone-else") == []
