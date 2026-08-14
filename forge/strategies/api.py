from __future__ import annotations

import dataclasses

from aiohttp import web

from forge.strategies.models import StrategySource
from forge.strategies.service import StrategyService
from forge.strategies.templates import FINANCEX_TEMPLATES


def _strategy_json(strategy) -> dict:
    data = dataclasses.asdict(strategy)
    data["source"] = strategy.source.value
    data["status"] = strategy.status.value
    return data


def register_routes(app: web.Application, service: StrategyService) -> None:
    async def list_templates(_request: web.Request) -> web.Response:
        return web.json_response(
            [{"source": source.value, **template} for source, template in FINANCEX_TEMPLATES.items()]
        )

    async def create_strategy(request: web.Request) -> web.Response:
        body = await request.json()
        user_id = body.get("user_id")
        source = body.get("source")
        if not user_id or not source:
            return web.json_response({"error": "user_id and source are required"}, status=400)

        if source == StrategySource.OWN.value:
            description = (body.get("description") or "").strip()
            if not description:
                return web.json_response({"error": "description is required for source=OWN"}, status=400)
            strategy = await service.create_own_strategy(
                user_id=user_id, name=body.get("name") or "Minha estratégia", description=description
            )
        else:
            try:
                strategy_source = StrategySource(source)
            except ValueError:
                return web.json_response({"error": f"unknown source: {source}"}, status=400)
            if strategy_source not in FINANCEX_TEMPLATES:
                return web.json_response({"error": f"unknown source: {source}"}, status=400)
            strategy = await service.select_financex_strategy(user_id=user_id, source=strategy_source)

        return web.json_response(_strategy_json(strategy), status=201)

    async def list_strategies(request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        strategies = await service.list_strategies(user_id)
        return web.json_response([_strategy_json(s) for s in strategies])

    app.router.add_get("/strategies/templates", list_templates)
    app.router.add_post("/strategies", create_strategy)
    app.router.add_get("/strategies", list_strategies)
