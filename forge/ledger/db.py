from __future__ import annotations

import uuid

import aiosqlite

from forge.ledger.models import StrategyTrade, Trade

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    exchange TEXT NOT NULL,
    external_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    market_type TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fee REAL NOT NULL,
    gross_pnl REAL,
    net_pnl REAL,
    funding REAL,
    slippage REAL,
    order_id TEXT NOT NULL,
    opened_at REAL NOT NULL,
    source TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    UNIQUE(exchange, external_id)
);
CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id);

CREATE TABLE IF NOT EXISTS strategy_trades (
    strategy_trade_id TEXT PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,
    strategy_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    classification TEXT NOT NULL
);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _row_to_trade(row: aiosqlite.Row) -> Trade:
    return Trade(
        trade_id=row["trade_id"],
        user_id=row["user_id"],
        exchange=row["exchange"],
        external_id=row["external_id"],
        symbol=row["symbol"],
        market_type=row["market_type"],
        side=row["side"],
        quantity=row["quantity"],
        price=row["price"],
        fee=row["fee"],
        gross_pnl=row["gross_pnl"],
        net_pnl=row["net_pnl"],
        funding=row["funding"],
        slippage=row["slippage"],
        order_id=row["order_id"],
        opened_at=row["opened_at"],
        source=row["source"],
        verification_status=row["verification_status"],
    )


class TradesRepo:
    """Append-only by construction: no update/delete methods exist here.
    insert_if_new relies on the (exchange, external_id) UNIQUE constraint
    so repeated syncs of the same fills are idempotent no-ops instead of
    duplicate rows."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def insert_if_new(self, trade: Trade) -> bool:
        """Returns True if this trade was newly inserted, False if it
        already existed (same exchange + external_id)."""
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO trades (
                    trade_id, user_id, exchange, external_id, symbol, market_type, side,
                    quantity, price, fee, gross_pnl, net_pnl, funding, slippage,
                    order_id, opened_at, source, verification_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.trade_id,
                    trade.user_id,
                    trade.exchange,
                    trade.external_id,
                    trade.symbol,
                    trade.market_type,
                    trade.side,
                    trade.quantity,
                    trade.price,
                    trade.fee,
                    trade.gross_pnl,
                    trade.net_pnl,
                    trade.funding,
                    trade.slippage,
                    trade.order_id,
                    trade.opened_at,
                    trade.source,
                    trade.verification_status,
                ),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def list_for_user(self, user_id: str) -> list[Trade]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM trades WHERE user_id = ? ORDER BY opened_at DESC", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_trade(r) for r in rows]


class StrategyTradesRepo:
    def __init__(self, db_path: str):
        self._db_path = db_path

    async def create(self, *, trade_id: str, strategy_id: str, origin: str, classification: str) -> StrategyTrade:
        strategy_trade_id = str(uuid.uuid4())
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO strategy_trades (
                    strategy_trade_id, trade_id, strategy_id, origin, classification
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (strategy_trade_id, trade_id, strategy_id, origin, classification),
            )
            await db.commit()
        return StrategyTrade(
            strategy_trade_id=strategy_trade_id,
            trade_id=trade_id,
            strategy_id=strategy_id,
            origin=origin,
            classification=classification,
        )

    async def get_for_trade(self, trade_id: str) -> StrategyTrade | None:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM strategy_trades WHERE trade_id = ?", (trade_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        return StrategyTrade(
            strategy_trade_id=row["strategy_trade_id"],
            trade_id=row["trade_id"],
            strategy_id=row["strategy_id"],
            origin=row["origin"],
            classification=row["classification"],
        )
