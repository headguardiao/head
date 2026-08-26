import time

import pytest

from forge.engine.glassnode_client import GlassnodeClient, MetricResult
from forge.engine.glassnode_sentiment import (
    COMPONENT_KEYS,
    _score_mvrv,
    _score_nupl,
    _score_sopr,
    compute_glassnode_sentiment,
)


def test_score_sopr_direction():
    assert _score_sopr(1.25) > 0  # profit realized without panic -> risk on lean
    assert _score_sopr(0.75) < 0  # realized losses -> risk off lean
    assert _score_sopr(1.0) == 0


def test_score_mvrv_direction():
    assert _score_mvrv(0.5) > 0  # undervalued -> risk on lean
    assert _score_mvrv(3.5) < 0  # overheated -> risk off lean


def test_score_nupl_direction():
    assert _score_nupl(0.1) > 0  # capitulation/fear zone -> risk on lean
    assert _score_nupl(0.9) < 0  # euphoria/greed -> risk off lean


@pytest.mark.asyncio
async def test_no_api_key_degrades_cleanly():
    client = GlassnodeClient(api_key="")
    result = await compute_glassnode_sentiment("BTCUSDT", client=client)

    assert result["has_key"] is False
    assert set(result["components"].keys()) == set(COMPONENT_KEYS)
    assert all(c["avail"] is False for c in result["components"].values())
    assert result["glassnode_bias"] == "NEUTRAL"
    assert result["glassnode_confidence"] == 0.0


@pytest.mark.asyncio
async def test_unauthorized_key_degrades_cleanly(monkeypatch):
    client = GlassnodeClient(api_key="bad-key")

    async def fake_ensure_key_valid():
        return False

    monkeypatch.setattr(client, "ensure_key_valid", fake_ensure_key_valid)

    result = await compute_glassnode_sentiment("BTCUSDT", client=client)

    assert result["has_key"] is True
    assert all(c["avail"] is False for c in result["components"].values())
    assert "glassnode unauthorized" in result["notes"]


@pytest.mark.asyncio
async def test_full_components_available_computes_score(monkeypatch):
    client = GlassnodeClient(api_key="good-key")
    now = int(time.time())

    async def fake_ensure_key_valid():
        return True

    single_value_by_path = {
        "/v1/metrics/indicators/sopr": 1.2,
        "/v1/metrics/indicators/sopr_less_155": 1.1,
        "/v1/metrics/market/mvrv": 0.8,
        "/v1/metrics/market/mvrv_less_155": 0.9,
        "/v1/metrics/indicators/net_unrealized_profit_loss": 0.2,
        "/v1/metrics/distribution/exchange_net_position_change": -500.0,
    }
    delta_series_by_path = {
        "/v1/metrics/distribution/balance_exchanges": (1000.0, 900.0),
        "/v1/metrics/distribution/supply_stablecoins_sum": (100_000.0, 105_000.0),
    }

    async def fake_get_metric(path, asset, interval="1h"):
        if path in delta_series_by_path:
            start, end = delta_series_by_path[path]
            points = [{"t": now - 86400, "v": start}, {"t": now, "v": end}]
            return MetricResult(points, interval, None)
        v = single_value_by_path.get(path)
        if v is None:
            return MetricResult(None, interval, "glassnode metric not found")
        points = [{"t": now - 86400, "v": v}, {"t": now, "v": v}]
        return MetricResult(points, interval, None)

    monkeypatch.setattr(client, "ensure_key_valid", fake_ensure_key_valid)
    monkeypatch.setattr(client, "get_metric", fake_get_metric)

    result = await compute_glassnode_sentiment("BTCUSDT", client=client)

    assert result["has_key"] is True
    assert result["asset_used"] == "BTC"
    assert result["asset_direct"] is True
    assert all(c["avail"] for c in result["components"].values())
    assert result["glassnode_confidence"] == 100.0
    assert -100.0 <= result["glassnode_score"] <= 100.0
    assert result["glassnode_bias"] in {"RISK_ON", "RISK_OFF", "NEUTRAL"}


@pytest.mark.asyncio
async def test_alt_symbol_anchors_on_btc(monkeypatch):
    client = GlassnodeClient(api_key="good-key")

    async def fake_ensure_key_valid():
        return True

    async def fake_get_metric(path, asset, interval="1h"):
        assert asset == "BTC"  # alts must never call Glassnode with their own ticker
        return MetricResult(None, interval, "glassnode metric not found")

    monkeypatch.setattr(client, "ensure_key_valid", fake_ensure_key_valid)
    monkeypatch.setattr(client, "get_metric", fake_get_metric)

    result = await compute_glassnode_sentiment("SOLUSDT", client=client)

    assert result["asset_used"] == "BTC"
    assert result["asset_direct"] is False
