from __future__ import annotations

from typing import Callable

import aiohttp

from forge.accounts.crypto import decrypt_secret, encrypt_secret
from forge.accounts.db import ConnectionsRepo
from forge.accounts.models import (
    Balance,
    ConnectionStatus,
    ExchangeConnection,
    InvalidCredentialsError,
    OpenOrder,
    Position,
    RawFill,
    SUPPORTED_EXCHANGES,
)
from forge.accounts.private_clients import CLIENT_CLASSES
from forge.accounts.private_clients.base import PrivateExchangeClient

ClientFactory = Callable[[str, str, str, str | None, aiohttp.ClientSession], PrivateExchangeClient]


def _default_client_factory(
    exchange: str, api_key: str, api_secret: str, passphrase: str | None, http: aiohttp.ClientSession
) -> PrivateExchangeClient:
    return CLIENT_CLASSES[exchange](api_key, api_secret, passphrase, http)


class ConnectionNotFoundError(Exception):
    pass


class AccountsService:
    """Application-level operations for private exchange connections.

    Takes an injectable client_factory so tests can swap in a fake
    PrivateExchangeClient instead of making real signed HTTP calls -
    see tests/accounts/test_service.py.
    """

    def __init__(self, repo: ConnectionsRepo, client_factory: ClientFactory = _default_client_factory):
        self._repo = repo
        self._client_factory = client_factory

    async def create_connection(
        self,
        *,
        user_id: str,
        exchange: str,
        api_key: str,
        api_secret: str,
        passphrase: str | None = None,
        label: str | None = None,
    ) -> ExchangeConnection:
        if exchange not in SUPPORTED_EXCHANGES:
            raise ValueError(f"unsupported exchange: {exchange}")

        async with aiohttp.ClientSession() as http:
            client = self._client_factory(exchange, api_key, api_secret, passphrase, http)
            try:
                await client.test_connection()
                status = ConnectionStatus.ACTIVE
            except InvalidCredentialsError:
                status = ConnectionStatus.INVALID

        connection = await self._repo.create(
            user_id=user_id,
            exchange=exchange,
            account_identifier=label or f"{exchange}-{user_id}",
            api_key_encrypted=encrypt_secret(api_key),
            api_secret_encrypted=encrypt_secret(api_secret),
            passphrase_encrypted=encrypt_secret(passphrase) if passphrase else None,
            status=status,
        )
        if status == ConnectionStatus.ACTIVE:
            await self._repo.touch_last_sync(connection.connection_id)
        return connection

    async def list_connections(self, user_id: str) -> list[ExchangeConnection]:
        return await self._repo.list_for_user(user_id)

    async def delete_connection(self, connection_id: str, user_id: str) -> bool:
        return await self._repo.delete(connection_id, user_id)

    async def get_balance(self, connection_id: str, user_id: str) -> Balance:
        scoped = await self._client_for(connection_id, user_id)
        async with scoped as client:
            return await client.get_balance()

    async def get_positions(self, connection_id: str, user_id: str) -> list[Position]:
        scoped = await self._client_for(connection_id, user_id)
        async with scoped as client:
            return await client.get_positions()

    async def get_open_orders(self, connection_id: str, user_id: str) -> list[OpenOrder]:
        scoped = await self._client_for(connection_id, user_id)
        async with scoped as client:
            return await client.get_open_orders()

    async def get_recent_trades(self, connection_id: str, user_id: str) -> list[RawFill]:
        scoped = await self._client_for(connection_id, user_id)
        async with scoped as client:
            return await client.get_recent_trades()

    async def _client_for(self, connection_id: str, user_id: str) -> "_ScopedClient":
        connection = await self._repo.get(connection_id, user_id)
        if connection is None:
            raise ConnectionNotFoundError(connection_id)
        creds = await self._repo.get_credentials(connection_id, user_id)
        if creds is None:
            raise ConnectionNotFoundError(connection_id)
        api_key_enc, api_secret_enc, passphrase_enc = creds
        api_key = decrypt_secret(api_key_enc)
        api_secret = decrypt_secret(api_secret_enc)
        passphrase = decrypt_secret(passphrase_enc) if passphrase_enc else None
        return _ScopedClient(self, connection_id, connection.exchange, api_key, api_secret, passphrase)


class _ScopedClient:
    """Owns the aiohttp session + PrivateExchangeClient for a single call
    and touches last_sync on successful exit, so every read path in
    AccountsService shares the same lifecycle/bookkeeping."""

    def __init__(
        self,
        service: AccountsService,
        connection_id: str,
        exchange: str,
        api_key: str,
        api_secret: str,
        passphrase: str | None,
    ):
        self._service = service
        self._connection_id = connection_id
        self._exchange = exchange
        self._api_key = api_key
        self._api_secret = api_secret
        self._passphrase = passphrase
        self._http: aiohttp.ClientSession | None = None
        self._client: PrivateExchangeClient | None = None

    async def __aenter__(self) -> PrivateExchangeClient:
        self._http = aiohttp.ClientSession()
        self._client = self._service._client_factory(
            self._exchange, self._api_key, self._api_secret, self._passphrase, self._http
        )
        return self._client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            await self._service._repo.touch_last_sync(self._connection_id)
        if self._http:
            await self._http.close()
