from __future__ import annotations

import dataclasses

from aiohttp import web

from forge.insights.service import InsightsService


def register_routes(app: web.Application, service: InsightsService) -> None:
    async def generate(request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        insights = await service.generate(user_id)
        return web.json_response([dataclasses.asdict(i) for i in insights])

    async def list_insights(request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        insights = await service.list_insights(user_id)
        return web.json_response([dataclasses.asdict(i) for i in insights])

    app.router.add_post("/insights/generate", generate)
    app.router.add_get("/insights", list_insights)
