from __future__ import annotations

import dataclasses

from aiohttp import web

from forge.accounts.models import InvalidCredentialsError
from forge.accounts.service import ConnectionNotFoundError
from forge.ledger.service import LedgerService


def register_routes(app: web.Application, service: LedgerService) -> None:
    async def sync_trades(request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        connection_id = request.match_info["connection_id"]
        try:
            new_count = await service.sync_trades(connection_id, user_id)
        except ConnectionNotFoundError:
            return web.json_response({"error": "connection not found"}, status=404)
        except InvalidCredentialsError as exc:
            return web.json_response({"error": f"credentials rejected by exchange: {exc}"}, status=401)
        except RuntimeError as exc:
            return web.json_response({"error": f"exchange call failed: {exc}"}, status=502)
        return web.json_response({"new_trades": new_count})

    async def list_trades(request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        trades = await service.list_trades(user_id)
        return web.json_response([dataclasses.asdict(t) for t in trades])

    app.router.add_post("/accounts/connections/{connection_id}/sync-trades", sync_trades)
    app.router.add_get("/trades", list_trades)
