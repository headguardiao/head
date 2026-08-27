import pytest

from forge.strategies.db import StrategiesRepo, init_db
from forge.strategies.models import StrategySource, StrategyStatus
from forge.strategies.service import StrategyService


@pytest.fixture
async def service(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return StrategyService(StrategiesRepo(db_path))


async def test_create_own_strategy_is_active(service):
    strategy = await service.create_own_strategy(user_id="u1", name="Minha", description="Compro no pullback")
    assert strategy.source == StrategySource.OWN
    assert strategy.status == StrategyStatus.ACTIVE
    assert strategy.activated_at is not None


async def test_select_financex_strategy_uses_template(service):
    strategy = await service.select_financex_strategy(user_id="u1", source=StrategySource.FINANCEX_ELITE)
    assert strategy.name == "FinanceX Elite"
    assert "pullback" in strategy.description.lower()


async def test_activating_new_strategy_archives_previous(service):
    first = await service.create_own_strategy(user_id="u1", name="A", description="desc A")
    second = await service.select_financex_strategy(user_id="u1", source=StrategySource.FINANCEX_NORMAL)

    strategies = {s.strategy_id: s for s in await service.list_strategies("u1")}
    assert strategies[first.strategy_id].status == StrategyStatus.ARCHIVED
    assert strategies[second.strategy_id].status == StrategyStatus.ACTIVE


async def test_only_one_active_strategy_at_a_time(service):
    await service.create_own_strategy(user_id="u1", name="A", description="desc A")
    await service.create_own_strategy(user_id="u1", name="B", description="desc B")
    await service.create_own_strategy(user_id="u1", name="C", description="desc C")

    active = [s for s in await service.list_strategies("u1") if s.status == StrategyStatus.ACTIVE]
    assert len(active) == 1
    assert active[0].name == "C"


async def test_get_active_strategy_returns_none_when_no_strategy(service):
    assert await service.get_active_strategy("brand-new-user") is None


async def test_strategies_are_scoped_to_user(service):
    await service.create_own_strategy(user_id="u1", name="A", description="desc A")
    await service.create_own_strategy(user_id="u2", name="B", description="desc B")

    assert len(await service.list_strategies("u1")) == 1
    assert len(await service.list_strategies("u2")) == 1
