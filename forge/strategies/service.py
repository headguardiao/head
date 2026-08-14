from __future__ import annotations

from forge.strategies.db import StrategiesRepo
from forge.strategies.models import Strategy, StrategySource
from forge.strategies.templates import FINANCEX_TEMPLATES


class StrategyService:
    def __init__(self, repo: StrategiesRepo):
        self._repo = repo

    async def create_own_strategy(self, *, user_id: str, name: str, description: str) -> Strategy:
        return await self._repo.create_active(
            user_id=user_id, source=StrategySource.OWN, name=name, description=description
        )

    async def select_financex_strategy(self, *, user_id: str, source: StrategySource) -> Strategy:
        template = FINANCEX_TEMPLATES[source]
        return await self._repo.create_active(
            user_id=user_id, source=source, name=template["name"], description=template["description"]
        )

    async def list_strategies(self, user_id: str) -> list[Strategy]:
        return await self._repo.list_for_user(user_id)

    async def get_active_strategy(self, user_id: str) -> Strategy | None:
        return await self._repo.get_active_for_user(user_id)
