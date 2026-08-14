from __future__ import annotations

import dataclasses
import logging

from aiohttp import web

from forge.accounts.models import InvalidCredentialsError, SUPPORTED_EXCHANGES
from forge.accounts.service import AccountsService, ConnectionNotFoundError

logger = logging.getLogger(__name__)


def _connection_json(conn) -> dict:
    data = dataclasses.asdict(conn)
    data["permissions"] = conn.permissions.value
    data["status"] = conn.status.value
    return data


def register_routes(app: web.Application, service: AccountsService) -> None:
    async def create_connection(request: web.Request) -> web.Response:
        body = await request.json()
        user_id = body.get("user_id")
        exchange = body.get("exchange")
        api_key = body.get("api_key")
        api_secret = body.get("api_secret")
        if not all([user_id, exchange, api_key, api_secret]):
            return web.json_response(
                {"error": "user_id, exchange, api_key and api_secret are required"}, status=400
            )
        if exchange not in SUPPORTED_EXCHANGES:
            return web.json_response({"error": f"unsupported exchange: {exchange}"}, status=400)
        try:
            connection = await service.create_connection(
                user_id=user_id,
                exchange=exchange,
                api_key=api_key,
                api_secret=api_secret,
                passphrase=body.get("passphrase"),
                label=body.get("label"),
            )
        except RuntimeError as exc:
            # Validation call to the exchange failed for a reason other
            # than bad credentials (rate limit, exchange outage, ...) -
            # a clean 502 instead of letting it fall through to aiohttp's
            # default non-JSON 500 body, which breaks JSON-parsing callers.
            logger.warning("connection validation call failed: %s", exc)
            return web.json_response({"error": f"exchange call failed: {exc}"}, status=502)
        return web.json_response(_connection_json(connection), status=201)

    async def list_connections(request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        connections = await service.list_connections(user_id)
        return web.json_response([_connection_json(c) for c in connections])

    async def delete_connection(request: web.Request) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        connection_id = request.match_info["connection_id"]
        deleted = await service.delete_connection(connection_id, user_id)
        if not deleted:
            return web.json_response({"error": "connection not found"}, status=404)
        return web.json_response({"status": "deleted"})

    async def get_balance(request: web.Request) -> web.Response:
        return await _sync_call(request, service.get_balance, lambda b: dataclasses.asdict(b))

    async def get_positions(request: web.Request) -> web.Response:
        return await _sync_call(request, service.get_positions, lambda ps: [dataclasses.asdict(p) for p in ps])

    async def get_open_orders(request: web.Request) -> web.Response:
        return await _sync_call(request, service.get_open_orders, lambda os_: [dataclasses.asdict(o) for o in os_])

    async def _sync_call(request: web.Request, method, to_json) -> web.Response:
        user_id = request.query.get("user_id")
        if not user_id:
            return web.json_response({"error": "user_id query param is required"}, status=400)
        connection_id = request.match_info["connection_id"]
        try:
            result = await method(connection_id, user_id)
        except ConnectionNotFoundError:
            return web.json_response({"error": "connection not found"}, status=404)
        except InvalidCredentialsError as exc:
            return web.json_response({"error": f"credentials rejected by exchange: {exc}"}, status=401)
        return web.json_response(to_json(result))

    app.router.add_post("/accounts/connections", create_connection)
    app.router.add_get("/accounts/connections", list_connections)
    app.router.add_delete("/accounts/connections/{connection_id}", delete_connection)
    app.router.add_get("/accounts/connections/{connection_id}/balance", get_balance)
    app.router.add_get("/accounts/connections/{connection_id}/positions", get_positions)
    app.router.add_get("/accounts/connections/{connection_id}/orders", get_open_orders)
