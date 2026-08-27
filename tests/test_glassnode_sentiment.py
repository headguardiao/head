import time

import pytest

from forge.engine.glassnode_client import GlassnodeClient, MetricResult
from forge.engine.glassnode_sentiment import (
    COMPONENT_KEYS,
    _score_mvrv,
    _score_nupl,
    _score_sopr,
    _score_sth_mvrv,
    _score_sth_sopr,
    compute_glassnode_sentiment,
    evaluate_glassnode_gate,
)


def test_score_sopr_direction_and_notes():
    notes = []
    assert _score_sopr(1.25, notes) < 0  # profit taking / distribution -> risk off lean
    assert "sopr: profit taking" in notes

    notes = []
    assert _score_sopr(0.75, notes) > 0  # capitulation spend -> risk on lean (contrarian)
    assert "sopr: capitulation spend" in notes


def test_score_sth_sopr_direction():
    assert _score_sth_sopr(1.25) < 0
    assert _score_sth_sopr(0.75) > 0


def test_score_mvrv_direction_and_notes():
    notes = []
    assert _score_mvrv(0.5, notes) > 0  # undervalued -> risk on lean
    notes = []
    assert _score_mvrv(3.5, notes) < 0  # overheated -> risk off lean
    assert "mvrv: euphoria" in notes

    notes = []
    _score_mvrv(0.5, notes)
    assert "mvrv: fear" in notes


def test_score_sth_mvrv_direction():
    assert _score_sth_mvrv(0.5) > 0
    assert _score_sth_mvrv(2.0) < 0


def test_score_nupl_direction():
    assert _score_nupl(0.1) > 0  # below the .25 center -> risk on lean
    assert _score_nupl(0.9) < 0  # well above it -> risk off lean


@pytest.mark.asyncio
async def test_no_api_key_degrades_cleanly():
    client = GlassnodeClient(api_key="")
    result = await compute_glassnode_sentiment("BTCUSDT", client=client)

    assert result["has_key"] is False
    assert set(result["components"].keys()) == set(COMPONENT_KEYS)
    assert all(c["avail"] is False for c in result["components"].values())
    assert result["glassnode_bias"] == "NEUTRAL"
    assert result["glassnode_confidence"] == 0.0
    assert result["profile"] == "30m"


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


def _make_fake_client_with_full_data():
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
        if path == "/v1/metrics/distribution/exchange_net_position_change":
            points = [{"t": now - i * 3600, "v": -100.0 * i} for i in range(7, 0, -1)]
            return MetricResult(points, interval, None)
        v = single_value_by_path.get(path)
        if v is None:
            return MetricResult(None, interval, "glassnode metric not found")
        points = [{"t": now - 86400, "v": v}, {"t": now, "v": v}]
        return MetricResult(points, interval, None)

    client.ensure_key_valid = fake_ensure_key_valid
    client.get_metric = fake_get_metric
    return client


@pytest.mark.asyncio
async def test_full_components_available_computes_weighted_score(monkeypatch):
    client = _make_fake_client_with_full_data()

    result = await compute_glassnode_sentiment("BTCUSDT", client=client)

    assert result["has_key"] is True
    assert result["asset_used"] == "BTC"
    assert result["asset_direct"] is True
    assert result["profile"] == "30m"
    assert all(c["avail"] for c in result["components"].values())
    assert result["glassnode_confidence"] == 100.0
    assert -100.0 <= result["glassnode_score"] <= 100.0


@pytest.mark.asyncio
async def test_profile_selection_changes_the_weighting(monkeypatch):
    client = _make_fake_client_with_full_data()

    monkeypatch.delenv("FORGE_SENTIMENT_PROFILE", raising=False)
    result_30m = await compute_glassnode_sentiment("BTCUSDT", client=client)

    monkeypatch.setenv("FORGE_SENTIMENT_PROFILE", "2h")
    result_2h = await compute_glassnode_sentiment("BTCUSDT", client=client)

    assert result_30m["profile"] == "30m"
    assert result_2h["profile"] == "2h"
    # Different weight tables over non-trivial, differing component
    # scores should not coincidentally produce the exact same average.
    assert result_30m["glassnode_score"] != result_2h["glassnode_score"]


@pytest.mark.asyncio
async def test_unknown_profile_falls_back_to_30m(monkeypatch):
    client = GlassnodeClient(api_key="")
    monkeypatch.setenv("FORGE_SENTIMENT_PROFILE", "weekly")
    result = await compute_glassnode_sentiment("BTCUSDT", client=client)
    assert result["profile"] == "30m"


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


@pytest.mark.asyncio
async def test_close_time_excludes_future_points():
    client = GlassnodeClient(api_key="good-key")
    now = int(time.time())
    cutoff = now - 3600

    async def fake_ensure_key_valid():
        return True

    async def fake_get_metric(path, asset, interval="1h"):
        if path == "/v1/metrics/indicators/sopr":
            points = [{"t": cutoff - 60, "v": 1.1}, {"t": now, "v": 999.0}]  # 999 would be an obvious tell if leaked
            return MetricResult(points, interval, None)
        return MetricResult(None, interval, "glassnode metric not found")

    client.ensure_key_valid = fake_ensure_key_valid
    client.get_metric = fake_get_metric

    result = await compute_glassnode_sentiment("BTCUSDT", client=client, close_time=cutoff)
    assert result["components"]["sopr"]["value"] == 1.1


def test_gate_off_by_default_always_allows():
    assert evaluate_glassnode_gate({}, -50, 100, "LONG", enabled=False) == "allow"


def test_gate_blocks_long_on_low_score():
    assert evaluate_glassnode_gate({}, -12, 100, "LONG", enabled=True) == "block"


def test_gate_blocks_long_on_profit_distribution_combo():
    components = {"sopr": {"value": 1.1}, "sth_mvrv": {"value": 1.3}}
    assert evaluate_glassnode_gate(components, 0, 100, "LONG", enabled=True) == "block"


def test_gate_blocks_long_on_mvrv_euphoria():
    components = {"mvrv": {"value": 2.5}}
    assert evaluate_glassnode_gate(components, 0, 100, "LONG", enabled=True) == "block"


def test_gate_blocks_long_on_extreme_negative_netflow_score():
    components = {"exch_netflow": {"score": -60}}
    assert evaluate_glassnode_gate(components, 0, 100, "LONG", enabled=True) == "block"


def test_gate_blocks_short_on_high_score():
    assert evaluate_glassnode_gate({}, 28, 100, "SHORT", enabled=True) == "block"


def test_gate_blocks_short_on_sth_sopr_and_netflow_combo():
    components = {"sth_sopr": {"value": 0.9}, "exch_netflow": {"score": 60}}
    assert evaluate_glassnode_gate(components, 0, 100, "SHORT", enabled=True) == "block"


def test_gate_reduces_on_neutral_with_confidence():
    assert evaluate_glassnode_gate({}, 0, 60, "LONG", enabled=True) == "reduce"


def test_gate_allows_when_nothing_triggers():
    assert evaluate_glassnode_gate({}, 5, 20, "LONG", enabled=True) == "allow"
