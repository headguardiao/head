from __future__ import annotations

from forge.insights.db import InsightsRepo
from forge.insights.engine import compute_insights
from forge.insights.models import Insight
from forge.ledger.db import StrategyTradesRepo, TradesRepo


class InsightsService:
    def __init__(self, insights_repo: InsightsRepo, trades_repo: TradesRepo, strategy_trades_repo: StrategyTradesRepo):
        self._insights_repo = insights_repo
        self._trades_repo = trades_repo
        self._strategy_trades_repo = strategy_trades_repo

    async def generate(self, user_id: str) -> list[Insight]:
        trades = await self._trades_repo.list_for_user(user_id)
        strategy_trades_map = await self._strategy_trades_repo.map_for_trade_ids([t.trade_id for t in trades])
        insights = compute_insights(user_id, trades, strategy_trades_map)
        for insight in insights:
            await self._insights_repo.create(insight)
        return insights

    async def list_insights(self, user_id: str) -> list[Insight]:
        return await self._insights_repo.list_for_user(user_id)
