"""Confirms every error path in forge/accounts/api.py returns a JSON
{"error": ...} body with the right status - including malformed request
bodies, which previously fell through to aiohttp's default non-JSON 500
page (json.JSONDecodeError from request.json() was uncaught)."""

from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from forge.accounts.api import register_routes


@pytest.fixture
async def client():
    app = web.Application()
    register_routes(app, AsyncMock())
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


async def test_malformed_json_body_returns_400_json(client):
    resp = await client.post(
        "/accounts/connections", data="not valid json", headers={"Content-Type": "application/json"}
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_empty_body_returns_400_json(client):
    resp = await client.post("/accounts/connections", data="", headers={"Content-Type": "application/json"})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_json_array_instead_of_object_returns_400_json(client):
    resp = await client.post("/accounts/connections", json=["not", "an", "object"])
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_non_string_field_returns_400_json(client):
    resp = await client.post(
        "/accounts/connections",
        json={"user_id": 12345, "exchange": "binance", "api_key": "k", "api_secret": "s"},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_non_string_passphrase_returns_400_json(client):
    resp = await client.post(
        "/accounts/connections",
        json={"user_id": "u1", "exchange": "okx", "api_key": "k", "api_secret": "s", "passphrase": 123},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_missing_fields_returns_400_json(client):
    resp = await client.post("/accounts/connections", json={"user_id": "u1"})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_unsupported_exchange_returns_400_json(client):
    resp = await client.post(
        "/accounts/connections",
        json={"user_id": "u1", "exchange": "kraken", "api_key": "k", "api_secret": "s"},
    )
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_missing_user_id_query_param_returns_400_json(client):
    resp = await client.get("/accounts/connections")
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data
