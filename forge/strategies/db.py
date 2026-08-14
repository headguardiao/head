from __future__ import annotations

import time
import uuid

import aiosqlite

from forge.strategies.models import Strategy, StrategySource, StrategyStatus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    activated_at REAL
);
CREATE INDEX IF NOT EXISTS idx_strategies_user ON strategies(user_id);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _row_to_strategy(row: aiosqlite.Row) -> Strategy:
    return Strategy(
        strategy_id=row["strategy_id"],
        user_id=row["user_id"],
        source=StrategySource(row["source"]),
        name=row["name"],
        description=row["description"],
        status=StrategyStatus(row["status"]),
        created_at=row["created_at"],
        activated_at=row["activated_at"],
    )


class StrategiesRepo:
    """CRUD for the strategies table. `activate` enforces "one active
    strategy per user" by archiving whatever was previously active in the
    same transaction - see forge/strategies/service.py for why creation
    always activates immediately in this round (no draft/backtest step
    yet)."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def create_active(
        self, *, user_id: str, source: StrategySource, name: str, description: str
    ) -> Strategy:
        now = time.time()
        strategy_id = str(uuid.uuid4())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE strategies SET status = ? WHERE user_id = ? AND status = ?",
                (StrategyStatus.ARCHIVED.value, user_id, StrategyStatus.ACTIVE.value),
            )
            await db.execute(
                """
                INSERT INTO strategies (
                    strategy_id, user_id, source, name, description, status, created_at, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (strategy_id, user_id, source.value, name, description, StrategyStatus.ACTIVE.value, now, now),
            )
            await db.commit()
        return Strategy(
            strategy_id=strategy_id,
            user_id=user_id,
            source=source,
            name=name,
            description=description,
            status=StrategyStatus.ACTIVE,
            created_at=now,
            activated_at=now,
        )

    async def list_for_user(self, user_id: str) -> list[Strategy]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM strategies WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_strategy(r) for r in rows]

    async def get_active_for_user(self, user_id: str) -> Strategy | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM strategies WHERE user_id = ? AND status = ?",
                (user_id, StrategyStatus.ACTIVE.value),
            ) as cursor:
                row = await cursor.fetchone()
        return _row_to_strategy(row) if row else None
