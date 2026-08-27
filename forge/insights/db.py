from __future__ import annotations

import json

import aiosqlite

from forge.insights.models import Insight

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_insights (
    insight_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    evidence TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    generated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_insights_user ON ai_insights(user_id);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


def _row_to_insight(row: aiosqlite.Row) -> Insight:
    return Insight(
        insight_id=row["insight_id"],
        user_id=row["user_id"],
        category=row["category"],
        text=row["text"],
        evidence=json.loads(row["evidence"]),
        sample_size=row["sample_size"],
        generated_at=row["generated_at"],
    )


class InsightsRepo:
    def __init__(self, db_path: str):
        self._db_path = db_path

    async def create(self, insight: Insight) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO ai_insights (
                    insight_id, user_id, category, text, evidence, sample_size, generated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    insight.insight_id,
                    insight.user_id,
                    insight.category,
                    insight.text,
                    json.dumps(insight.evidence),
                    insight.sample_size,
                    insight.generated_at,
                ),
            )
            await db.commit()

    async def list_for_user(self, user_id: str) -> list[Insight]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM ai_insights WHERE user_id = ? ORDER BY generated_at DESC", (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [_row_to_insight(r) for r in rows]
