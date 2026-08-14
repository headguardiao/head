from __future__ import annotations

import time
import uuid

import aiosqlite

from forge.accounts.models import ConnectionStatus, ExchangeConnection, Permission

_SCHEMA = """
CREATE TABLE IF NOT EXISTS exchange_connections (
    connection_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    account_identifier TEXT NOT NULL,
    permissions TEXT NOT NULL,
    status TEXT NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    api_secret_encrypted TEXT NOT NULL,
    passphrase_encrypted TEXT,
    last_sync REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exchange_connections_user ON exchange_connections(user_id);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _row_to_connection(row: aiosqlite.Row) -> ExchangeConnection:
    return ExchangeConnection(
        connection_id=row["connection_id"],
        user_id=row["user_id"],
        exchange=row["exchange"],
        account_identifier=row["account_identifier"],
        permissions=Permission(row["permissions"]),
        status=ConnectionStatus(row["status"]),
        last_sync=row["last_sync"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ConnectionsRepo:
    """Thin async CRUD wrapper around the exchange_connections table.

    Opens a fresh aiosqlite connection per call rather than holding one
    open for the process lifetime, since this repo's app is a single
    long-running asyncio process already juggling several WS adapters -
    a short-lived connection per call keeps this module self-contained
    and avoids any shared-connection lifecycle coupling with app.py.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def create(
        self,
        *,
        user_id: str,
        exchange: str,
        account_identifier: str,
        api_key_encrypted: str,
        api_secret_encrypted: str,
        passphrase_encrypted: str | None,
        status: ConnectionStatus,
    ) -> ExchangeConnection:
        now = time.time()
        connection_id = str(uuid.uuid4())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO exchange_connections (
                    connection_id, user_id, exchange, account_identifier,
                    permissions, status, api_key_encrypted, api_secret_encrypted,
                    passphrase_encrypted, last_sync, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    connection_id,
                    user_id,
                    exchange,
                    account_identifier,
                    Permission.READ_ONLY.value,
                    status.value,
                    api_key_encrypted,
                    api_secret_encrypted,
                    passphrase_encrypted,
                    None,
                    now,
                    now,
                ),
            )
            await db.commit()
        return ExchangeConnection(
            connection_id=connection_id,
            user_id=user_id,
            exchange=exchange,
            account_identifier=account_identifier,
            permissions=Permission.READ_ONLY,
            status=status,
            last_sync=None,
            created_at=now,
            updated_at=now,
        )

    async def list_for_user(self, user_id: str) -> list[ExchangeConnection]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM exchange_connections WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_connection(r) for r in rows]

    async def get(self, connection_id: str, user_id: str) -> ExchangeConnection | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM exchange_connections WHERE connection_id = ? AND user_id = ?",
                (connection_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
        return _row_to_connection(row) if row else None

    async def get_credentials(self, connection_id: str, user_id: str) -> tuple[str, str, str | None] | None:
        """Returns (api_key_encrypted, api_secret_encrypted, passphrase_encrypted)."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT api_key_encrypted, api_secret_encrypted, passphrase_encrypted
                FROM exchange_connections WHERE connection_id = ? AND user_id = ?
                """,
                (connection_id, user_id),
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return row["api_key_encrypted"], row["api_secret_encrypted"], row["passphrase_encrypted"]

    async def update_status(self, connection_id: str, status: ConnectionStatus) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE exchange_connections SET status = ?, updated_at = ? WHERE connection_id = ?",
                (status.value, time.time(), connection_id),
            )
            await db.commit()

    async def touch_last_sync(self, connection_id: str) -> None:
        now = time.time()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE exchange_connections SET last_sync = ?, updated_at = ? WHERE connection_id = ?",
                (now, now, connection_id),
            )
            await db.commit()

    async def delete(self, connection_id: str, user_id: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "DELETE FROM exchange_connections WHERE connection_id = ? AND user_id = ?",
                (connection_id, user_id),
            )
            await db.commit()
            return cursor.rowcount > 0
