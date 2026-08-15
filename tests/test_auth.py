from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from forge.auth import build_auth_middleware


def _make_app(api_key):
    app = web.Application(middlewares=[build_auth_middleware(api_key)])

    async def ok(_request):
        return web.json_response({"ok": True})

    app.router.add_get("/health", ok)
    app.router.add_get("/signal/BTCUSDT", ok)
    app.router.add_get("/dashboard", ok)
    app.router.add_get("/", ok)
    app.router.add_get("/accounts/connections", ok)
    app.router.add_get("/trades", ok)
    return app


async def _client(api_key):
    server = TestServer(_make_app(api_key))
    client = TestClient(server)
    await client.start_server()
    return client


async def test_no_api_key_configured_allows_everything():
    client = await _client(None)
    try:
        for path in ("/health", "/accounts/connections", "/trades"):
            resp = await client.get(path)
            assert resp.status == 200
    finally:
        await client.close()


async def test_protected_endpoint_without_header_returns_401_json():
    client = await _client("secret-key")
    try:
        resp = await client.get("/accounts/connections")
        assert resp.status == 401
        data = await resp.json()
        assert "error" in data
    finally:
        await client.close()


async def test_protected_endpoint_with_wrong_key_returns_401():
    client = await _client("secret-key")
    try:
        resp = await client.get("/accounts/connections", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status == 401
    finally:
        await client.close()


async def test_protected_endpoint_with_correct_key_passes_through():
    client = await _client("secret-key")
    try:
        resp = await client.get("/accounts/connections", headers={"Authorization": "Bearer secret-key"})
        assert resp.status == 200
    finally:
        await client.close()


async def test_malformed_authorization_header_returns_401():
    client = await _client("secret-key")
    try:
        resp = await client.get("/accounts/connections", headers={"Authorization": "secret-key"})  # missing "Bearer "
        assert resp.status == 401
        resp2 = await client.get("/accounts/connections", headers={"Authorization": "Bearer "})
        assert resp2.status == 401
    finally:
        await client.close()


async def test_public_paths_work_without_key_even_when_configured():
    client = await _client("secret-key")
    try:
        for path in ("/health", "/signal/BTCUSDT", "/dashboard", "/"):
            resp = await client.get(path)
            assert resp.status == 200, path
    finally:
        await client.close()
