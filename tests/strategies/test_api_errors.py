"""Mirrors tests/accounts/test_api_errors.py for forge/strategies/api.py -
same malformed-request-body gap, same fix."""

from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from forge.strategies.api import register_routes


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
    resp = await client.post("/strategies", data="not valid json", headers={"Content-Type": "application/json"})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_json_array_instead_of_object_returns_400_json(client):
    resp = await client.post("/strategies", json=["not", "an", "object"])
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_non_string_source_returns_400_json(client):
    resp = await client.post("/strategies", json={"user_id": "u1", "source": 123})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_unknown_source_returns_400_json(client):
    resp = await client.post("/strategies", json={"user_id": "u1", "source": "NOT_A_REAL_SOURCE"})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_own_without_description_returns_400_json(client):
    resp = await client.post("/strategies", json={"user_id": "u1", "source": "OWN"})
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data


async def test_missing_user_id_query_param_returns_400_json(client):
    resp = await client.get("/strategies")
    assert resp.status == 400
    data = await resp.json()
    assert "error" in data
