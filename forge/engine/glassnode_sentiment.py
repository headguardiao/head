from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from forge.engine.glassnode_client import GlassnodeClient

# ADD-ONLY module: this file must never import from, or be imported by,
# score_engine.py / liquidity_engine.py. It only produces the sibling
# `glassnode` block added onto the /signal payload in interface.py - it
# never touches LIQUIDITY_SCORE, the PDF §7 weights, the 1.15x wall bias
# threshold, or the exchanges/3 confirmation confidence.

# Forge symbol -> Glassnode asset. Alts anchor on the BTC on-chain layer
# instead of scanning the Glassnode catalog at runtime (metadata calls
# are for the one-shot boot key check only).
_DIRECT_ASSETS = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

# Candidate paths tried in order per component; the first one that
# returns data wins. Confirm against GET /v1/metadata/metrics?a=BTC if
# any of these start 404ing - Glassnode has renamed paths before.
_METRIC_PATHS: dict[str, list[str]] = {
    "sopr": ["/v1/metrics/indicators/sopr"],
    "sth_sopr": [
        "/v1/metrics/indicators/sopr_less_155",
        "/v1/metrics/indicators/ssopr",
    ],
    "mvrv": ["/v1/metrics/market/mvrv"],
    "sth_mvrv": ["/v1/metrics/market/mvrv_less_155"],
    "nupl": [
        "/v1/metrics/indicators/net_unrealized_profit_loss",
        "/v1/metrics/market/nupl_more_155",
    ],
    "exch_netflow": [
        "/v1/metrics/distribution/exchange_net_position_change",
        "/v1/metrics/transactions/transfers_volume_exchanges_net",
    ],
    "exch_reserve_d1": ["/v1/metrics/distribution/balance_exchanges"],
    "stables": ["/v1/metrics/distribution/supply_stablecoins_sum"],
}

COMPONENT_KEYS = list(_METRIC_PATHS.keys())  # exactly 8 - matches the max/cycle budget

# Heuristic calibration constants for the -100..+100 component scores.
# These are directional lean formulas, not a validated trading model -
# tune them once real series magnitudes are observed in production.
_NETFLOW_SATURATION_BTC = 2000.0


def _clamp(value: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _score_sopr(value: float) -> float:
    # SOPR > 1: coins moving on-chain in profit without panic (healthy) -> RISK_ON.
    # SOPR < 1: realized losses / capitulation -> RISK_OFF.
    return _clamp((value - 1.0) * 400.0)


def _score_mvrv(value: float) -> float:
    # ~1 = price at realized cost basis (neutral). Well below 1 =
    # historically undervalued/accumulation (RISK_ON); well above ~3.5 =
    # historically overheated/distribution (RISK_OFF).
    return _clamp((1.0 - value) * 40.0)


def _score_nupl(value: float) -> float:
    # Glassnode NUPL zones: <0 capitulation, 0-.25 hope/fear, .25-.5
    # optimism, .5-.75 belief, >.75 euphoria/greed. Centered on the
    # belief/euphoria boundary.
    return _clamp((0.5 - value) * 200.0)


def _score_netflow(value: float) -> float:
    # Positive netflow = coins moving TO exchanges (sell pressure building) -> RISK_OFF.
    # Negative netflow = coins leaving exchanges (accumulation) -> RISK_ON.
    return _clamp(-value / _NETFLOW_SATURATION_BTC * 100.0)


def _score_reserve_delta_pct(pct: float) -> float:
    # Falling exchange reserves (negative %) = coins leaving custody -> RISK_ON.
    return _clamp(-pct * 20.0)


def _score_stables_delta_pct(pct: float) -> float:
    # Growing stablecoin supply = more on-chain dry powder -> RISK_ON.
    return _clamp(pct * 20.0)


def _delta_pct_over_seconds(points: list[dict], window_seconds: float = 86400.0) -> Optional[float]:
    """% change between the last point and the point closest to
    `window_seconds` before it (spec: "penúltimo" is whichever prior
    point is closest to the 24h mark, not literally points[-2], since
    the array's spacing depends on the interval actually served)."""
    if len(points) < 2:
        return None
    last = points[-1]
    target_t = last["t"] - window_seconds
    prior = min(points[:-1], key=lambda p: abs(p["t"] - target_t))
    if prior["v"] == 0:
        return None
    return (last["v"] - prior["v"]) / abs(prior["v"]) * 100.0


def _value_score_sopr(points: list[dict]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_sopr(v)


def _value_score_mvrv(points: list[dict]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_mvrv(v)


def _value_score_nupl(points: list[dict]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_nupl(v)


def _value_score_netflow(points: list[dict]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_netflow(v)


def _value_score_reserve_d1(points: list[dict]) -> tuple[Optional[float], Optional[float]]:
    pct = _delta_pct_over_seconds(points)
    if pct is None:
        return None, None
    return pct, _score_reserve_delta_pct(pct)


def _value_score_stables(points: list[dict]) -> tuple[Optional[float], Optional[float]]:
    pct = _delta_pct_over_seconds(points)
    if pct is None:
        return None, None
    return points[-1]["v"], _score_stables_delta_pct(pct)


_VALUE_SCORE_FNS: dict[str, Callable[[list[dict]], tuple[Optional[float], Optional[float]]]] = {
    "sopr": _value_score_sopr,
    "sth_sopr": _value_score_sopr,
    "mvrv": _value_score_mvrv,
    "sth_mvrv": _value_score_mvrv,
    "nupl": _value_score_nupl,
    "exch_netflow": _value_score_netflow,
    "exch_reserve_d1": _value_score_reserve_d1,
    "stables": _value_score_stables,
}


def _resolve_asset(symbol: str) -> tuple[str, bool]:
    direct = _DIRECT_ASSETS.get(symbol.upper())
    if direct:
        return direct, True
    return "BTC", False


@dataclass
class _ComponentResult:
    value: Optional[float]
    score: Optional[float]
    avail: bool


def _empty_components() -> dict[str, dict]:
    return {k: {"value": None, "score": None, "avail": False} for k in COMPONENT_KEYS}


def _empty_payload(has_key: bool, notes: list[str]) -> dict:
    return {
        "has_key": has_key,
        "asof": int(time.time()),
        "asset_used": "BTC",
        "asset_direct": False,
        "interval": "1h",
        "glassnode_score": 0.0,
        "glassnode_bias": "NEUTRAL",
        "glassnode_confidence": 0.0,
        "components": _empty_components(),
        "notes": notes,
    }


async def _fetch_component(
    client: GlassnodeClient, key: str, asset: str, notes: list[str]
) -> tuple[_ComponentResult, str]:
    interval_used = "1h"
    last_note: Optional[str] = None
    for path in _METRIC_PATHS[key]:
        result = await client.get_metric(path, asset, "1h")
        interval_used = result.interval
        if result.points:
            value, score = _VALUE_SCORE_FNS[key](result.points)
            if value is not None and score is not None:
                return _ComponentResult(round(value, 6), round(score, 2), True), interval_used
            last_note = f"{key}: not enough history for delta yet"
            continue
        last_note = f"{key}: {result.note}"
    if last_note:
        notes.append(last_note)
    return _ComponentResult(None, None, False), interval_used


async def compute_glassnode_sentiment(symbol: str, client: Optional[GlassnodeClient] = None) -> dict:
    """Builds the `glassnode` sibling block for the /signal payload.
    Never raises - any failure (no key, bad key, network, rate limit)
    degrades to has_key=false / avail=false components so the endpoint
    still returns 200."""
    client = client or _default_client()
    notes: list[str] = []

    if not client.has_key:
        return _empty_payload(False, notes)

    key_ok = await client.ensure_key_valid()
    if not key_ok:
        notes.append("glassnode unauthorized")
        return _empty_payload(True, notes)

    asset, asset_direct = _resolve_asset(symbol)
    interval_used = "1h"
    components: dict[str, dict] = {}
    scores: list[float] = []

    for key in COMPONENT_KEYS:
        comp, iv = await _fetch_component(client, key, asset, notes)
        components[key] = {"value": comp.value, "score": comp.score, "avail": comp.avail}
        if iv == "24h":
            interval_used = "24h"
        if comp.avail and comp.score is not None:
            scores.append(comp.score)

    glassnode_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    confidence = round(len(scores) / len(COMPONENT_KEYS) * 100.0, 1)
    if not scores:
        bias = "NEUTRAL"
    elif glassnode_score > 15:
        bias = "RISK_ON"
    elif glassnode_score < -15:
        bias = "RISK_OFF"
    else:
        bias = "NEUTRAL"

    return {
        "has_key": True,
        "asof": int(time.time()),
        "asset_used": asset,
        "asset_direct": asset_direct,
        "interval": interval_used,
        "glassnode_score": glassnode_score,
        "glassnode_bias": bias,
        "glassnode_confidence": confidence,
        "components": components,
        "notes": notes,
    }


_client_singleton: Optional[GlassnodeClient] = None


def _default_client() -> GlassnodeClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = GlassnodeClient()
    return _client_singleton
