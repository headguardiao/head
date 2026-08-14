import pytest
from cryptography.fernet import Fernet

import forge.accounts.crypto as crypto
from forge.accounts.db import ConnectionsRepo
from forge.accounts.db import init_db as init_accounts_db
from forge.accounts.models import Balance, RawFill
from forge.accounts.service import AccountsService
from forge.ledger.db import StrategyTradesRepo, TradesRepo
from forge.ledger.db import init_db as init_ledger_db
from forge.ledger.service import LedgerService
from forge.strategies.db import StrategiesRepo
from forge.strategies.db import init_db as init_strategies_db
from forge.strategies.models import StrategySource
from forge.strategies.service import StrategyService


class FakePrivateClient:
    def __init__(self, api_key, api_secret, passphrase, http, *, fills):
        self.fills = fills

    async def test_connection(self):
        return await self.get_balance()

    async def get_balance(self):
        return Balance(exchange="binance", total_equity_usd=100.0, available_usd=90.0)

    async def get_positions(self):
        return []

    async def get_open_orders(self):
        return []

    async def get_recent_trades(self):
        return self.fills


def make_factory(fills):
    def factory(exchange, api_key, api_secret, passphrase, http):
        return FakePrivateClient(api_key, api_secret, passphrase, http, fills=fills)

    return factory


SAMPLE_FILLS = [
    RawFill(
        exchange="binance",
        external_id="1",
        symbol="BTCUSDT",
        side="BUY",
        qty=0.1,
        price=50000.0,
        fee=0.5,
        realized_pnl=10.0,
        order_id="order-1",
        timestamp=1700000000.0,
    ),
    RawFill(
        exchange="binance",
        external_id="2",
        symbol="ETHUSDT",
        side="SELL",
        qty=1.0,
        price=3000.0,
        fee=0.3,
        realized_pnl=None,
        order_id="order-2",
        timestamp=1700000100.0,
    ),
]


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    crypto._fernet = None
    monkeypatch.setenv("FORGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    yield
    crypto._fernet = None


@pytest.fixture
async def rig(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_accounts_db(db_path)
    await init_strategies_db(db_path)
    await init_ledger_db(db_path)

    accounts_service = AccountsService(ConnectionsRepo(db_path), client_factory=make_factory(SAMPLE_FILLS))
    strategy_service = StrategyService(StrategiesRepo(db_path))
    strategy_trades_repo = StrategyTradesRepo(db_path)
    ledger_service = LedgerService(accounts_service, TradesRepo(db_path), strategy_trades_repo, StrategiesRepo(db_path))
    connection = await accounts_service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    return connection, strategy_service, ledger_service, strategy_trades_repo


async def test_sync_stores_new_trades(rig):
    connection, _, ledger_service, _ = rig
    new_count = await ledger_service.sync_trades(connection.connection_id, "u1")
    assert new_count == 2
    assert len(await ledger_service.list_trades("u1")) == 2


async def test_resync_is_idempotent(rig):
    connection, _, ledger_service, _ = rig
    await ledger_service.sync_trades(connection.connection_id, "u1")
    second_count = await ledger_service.sync_trades(connection.connection_id, "u1")
    assert second_count == 0
    assert len(await ledger_service.list_trades("u1")) == 2


async def test_realized_pnl_maps_to_gross_and_net(rig):
    connection, _, ledger_service, _ = rig
    await ledger_service.sync_trades(connection.connection_id, "u1")
    trades = {t.external_id: t for t in await ledger_service.list_trades("u1")}
    assert trades["1"].gross_pnl == 10.0
    assert trades["1"].net_pnl == pytest.approx(9.5)
    assert trades["2"].gross_pnl is None
    assert trades["2"].net_pnl is None


async def test_trades_link_to_active_strategy(rig):
    connection, strategy_service, ledger_service, strategy_trades_repo = rig
    strategy = await strategy_service.select_financex_strategy(user_id="u1", source=StrategySource.FINANCEX_ELITE)
    await ledger_service.sync_trades(connection.connection_id, "u1")

    trades = await ledger_service.list_trades("u1")
    linked = await strategy_trades_repo.get_for_trade(trades[0].trade_id)
    assert linked is not None
    assert linked.strategy_id == strategy.strategy_id
    assert linked.origin == "FINANCEX_ELITE"
    assert linked.classification == "UNKNOWN"


async def test_trades_without_active_strategy_are_stored_unlinked(rig):
    connection, _, ledger_service, strategy_trades_repo = rig
    await ledger_service.sync_trades(connection.connection_id, "u1")
    trades = await ledger_service.list_trades("u1")
    assert await strategy_trades_repo.get_for_trade(trades[0].trade_id) is None
