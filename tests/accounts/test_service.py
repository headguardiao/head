import pytest
from cryptography.fernet import Fernet

import forge.accounts.crypto as crypto
from forge.accounts.db import ConnectionsRepo, init_db
from forge.accounts.models import Balance, ConnectionStatus, InvalidCredentialsError, OpenOrder, Position
from forge.accounts.service import AccountsService, ConnectionNotFoundError


class FakePrivateClient:
    def __init__(self, api_key, api_secret, passphrase, http, *, should_fail=False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.http = http
        self.should_fail = should_fail

    async def test_connection(self):
        return await self.get_balance()

    async def get_balance(self):
        if self.should_fail:
            raise InvalidCredentialsError("bad creds")
        return Balance(exchange="binance", total_equity_usd=100.0, available_usd=90.0)

    async def get_positions(self):
        return [
            Position(
                exchange="binance", symbol="BTCUSDT", side="LONG", size=1.0, entry_price=50000.0, unrealized_pnl=10.0
            )
        ]

    async def get_open_orders(self):
        return [
            OpenOrder(exchange="binance", order_id="1", symbol="BTCUSDT", side="BUY", price=50000.0, qty=0.1, status="NEW")
        ]


def make_factory(should_fail: bool = False):
    def factory(exchange, api_key, api_secret, passphrase, http):
        return FakePrivateClient(api_key, api_secret, passphrase, http, should_fail=should_fail)

    return factory


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    crypto._fernet = None
    monkeypatch.setenv("FORGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    yield
    crypto._fernet = None


@pytest.fixture
async def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return ConnectionsRepo(db_path)


async def test_create_connection_active_on_success(repo):
    service = AccountsService(repo, client_factory=make_factory(should_fail=False))
    conn = await service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    assert conn.status == ConnectionStatus.ACTIVE
    assert conn.user_id == "u1"
    assert conn.exchange == "binance"


async def test_create_connection_invalid_on_bad_creds(repo):
    service = AccountsService(repo, client_factory=make_factory(should_fail=True))
    conn = await service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    assert conn.status == ConnectionStatus.INVALID


async def test_create_connection_rejects_unsupported_exchange(repo):
    service = AccountsService(repo, client_factory=make_factory())
    with pytest.raises(ValueError):
        await service.create_connection(user_id="u1", exchange="kraken", api_key="k", api_secret="s")


async def test_list_connections_scoped_to_user(repo):
    service = AccountsService(repo, client_factory=make_factory())
    await service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    await service.create_connection(user_id="u2", exchange="bybit", api_key="k", api_secret="s")
    u1_connections = await service.list_connections("u1")
    assert len(u1_connections) == 1
    assert u1_connections[0].exchange == "binance"


async def test_list_connections_never_leaks_secrets(repo):
    service = AccountsService(repo, client_factory=make_factory())
    await service.create_connection(
        user_id="u1", exchange="binance", api_key="super-secret-key", api_secret="super-secret-value"
    )
    connections = await service.list_connections("u1")
    for value in vars(connections[0]).values():
        assert "super-secret" not in str(value)


async def test_get_balance_returns_fresh_data_and_updates_last_sync(repo):
    service = AccountsService(repo, client_factory=make_factory())
    conn = await service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    balance = await service.get_balance(conn.connection_id, "u1")
    assert balance.total_equity_usd == 100.0
    updated = (await service.list_connections("u1"))[0]
    assert updated.last_sync is not None


async def test_get_balance_unknown_connection_raises(repo):
    service = AccountsService(repo, client_factory=make_factory())
    with pytest.raises(ConnectionNotFoundError):
        await service.get_balance("does-not-exist", "u1")


async def test_get_positions_and_open_orders(repo):
    service = AccountsService(repo, client_factory=make_factory())
    conn = await service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    positions = await service.get_positions(conn.connection_id, "u1")
    orders = await service.get_open_orders(conn.connection_id, "u1")
    assert positions[0].symbol == "BTCUSDT"
    assert orders[0].order_id == "1"


async def test_delete_connection(repo):
    service = AccountsService(repo, client_factory=make_factory())
    conn = await service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    assert await service.delete_connection(conn.connection_id, "u1") is True
    assert await service.list_connections("u1") == []


async def test_delete_connection_scoped_to_user(repo):
    service = AccountsService(repo, client_factory=make_factory())
    conn = await service.create_connection(user_id="u1", exchange="binance", api_key="k", api_secret="s")
    assert await service.delete_connection(conn.connection_id, "someone-else") is False
