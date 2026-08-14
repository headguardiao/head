from __future__ import annotations

import abc

import aiohttp

from forge.accounts.models import Balance, OpenOrder, Position, RawFill


class PrivateExchangeClient(abc.ABC):
    """One authenticated REST client per exchange, mirroring the isolation
    principle of forge/adapters/base.py's public ExchangeAdapter: each
    exchange's signing scheme and quirks are contained to its own module.

    Every concrete client is READ-ONLY by construction - none of them
    implement order placement, cancellation, or withdrawal endpoints.
    """

    exchange: str = "base"

    def __init__(self, api_key: str, api_secret: str, passphrase: str | None, http: aiohttp.ClientSession):
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._http = http

    async def test_connection(self) -> Balance:
        """Validates the credentials by making a real read call. Raises
        InvalidCredentialsError on auth failure; lets network/HTTP errors
        propagate as-is so they aren't confused with bad credentials."""
        return await self.get_balance()

    @abc.abstractmethod
    async def get_balance(self) -> Balance: ...

    @abc.abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abc.abstractmethod
    async def get_open_orders(self) -> list[OpenOrder]: ...

    @abc.abstractmethod
    async def get_recent_trades(self) -> list[RawFill]:
        """Most recent fills/executions within whatever bounded window
        the exchange's endpoint returns by default - no pagination or
        full-history backfill (that's a separate, larger piece; see
        forge/ledger/service.py for how these get deduped on repeat
        calls)."""
