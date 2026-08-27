from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

from forge.engine.glassnode_client import GlassnodeClient

# ADD-ONLY module: this file must never import from, or be imported by,
# score_engine.py / liquidity_engine.py. It only produces the sibling
# `glassnode` block added onto the /signal payload in interface.py - it
# never touches LIQUIDITY_SCORE, the PDF §7 weights, the 1.15x wall bias
# threshold, or the exchanges/3 confirmation confidence.
#
# Sign convention (per the calibrated briefing spec): positivo =
# RISK_ON = acumulação / reserva saindo da exchange / gasto no
# prejuízo (capitulation spend is treated as a contrarian accumulation
# signal, NOT as fear) - this is the opposite of a naive "profit good,
# loss bad" reading, so don't "fix" the signs below without re-reading
# the spec.

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

BIAS_THRESHOLD = 15.0

# Weight profiles - priors calibrated on the operational (briefing
# section E), kept as config/data instead of inline in the formulas so
# they can be retuned without touching the scoring code. Selected via
# FORGE_SENTIMENT_PROFILE=30m|2h|daily (default 30m).
_WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "30m": {
        "exch_netflow": 0.26,
        "sth_sopr": 0.22,
        "exch_reserve_d1": 0.14,
        "sth_mvrv": 0.14,
        "sopr": 0.10,
        "mvrv": 0.06,
        "nupl": 0.05,
        "stables": 0.03,
    },
    "2h": {
        "mvrv": 0.18,
        "exch_netflow": 0.16,
        "sopr": 0.14,
        "sth_sopr": 0.14,
        "nupl": 0.14,
        "sth_mvrv": 0.10,
        "exch_reserve_d1": 0.10,
        "stables": 0.04,
    },
}
_WEIGHT_PROFILES["daily"] = _WEIGHT_PROFILES["2h"]  # spec: "Perfil 2h/daily (regime)" - same table


def _active_profile() -> str:
    profile = os.environ.get("FORGE_SENTIMENT_PROFILE", "30m")
    return profile if profile in _WEIGHT_PROFILES else "30m"


def _clamp(value: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _bias_from_score(score: float) -> str:
    if score >= BIAS_THRESHOLD:
        return "RISK_ON"
    if score <= -BIAS_THRESHOLD:
        return "RISK_OFF"
    return "NEUTRAL"


def _percentile(values: list[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile - good enough for a normalization
    reference, not a statistical claim."""
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(pct / 100.0 * len(ordered) + 0.999999) - 1))
    return ordered[idx]


def _filter_up_to(points: list[dict], close_time: Optional[int]) -> list[dict]:
    """Sem lookahead: quando o chamador (o alerta) passa closeTime, só
    pontos com t <= closeTime entram na leitura."""
    if close_time is None:
        return points
    filtered = [p for p in points if p["t"] <= close_time]
    return filtered


def _score_sopr(value: float, notes: list[str]) -> float:
    if value > 1.05:
        notes.append("sopr: profit taking")
    elif value < 0.98:
        notes.append("sopr: capitulation spend")
    return _clamp((1.0 - value) * 400.0)


def _score_sth_sopr(value: float) -> float:
    return _clamp((1.0 - value) * 350.0)


def _score_mvrv(value: float, notes: list[str]) -> float:
    if value >= 2.4:
        notes.append("mvrv: euphoria")
    elif value <= 0.85:
        notes.append("mvrv: fear")
    return _clamp((1.2 - value) * 50.0)


def _score_sth_mvrv(value: float) -> float:
    return _clamp((1.0 - value) * 80.0)


def _score_nupl(value: float) -> float:
    return _clamp((0.25 - value) * 200.0)


def _score_reserve_delta_pct(pct: float) -> float:
    # Falling exchange reserves (negative %) = coins leaving custody -> RISK_ON.
    return _clamp(-pct * 40.0)


def _score_stables_delta_pct(pct: float) -> float:
    # Growing stablecoin supply = more on-chain dry powder -> RISK_ON.
    return _clamp(pct * 12.0)


def _delta_pct_over_seconds(points: list[dict], window_seconds: float) -> Optional[float]:
    """% change between the last point and whichever prior point is
    closest to `window_seconds` before it (spacing depends on the
    interval actually served, so this isn't literally points[-2])."""
    if len(points) < 2:
        return None
    last = points[-1]
    target_t = last["t"] - window_seconds
    prior = min(points[:-1], key=lambda p: abs(p["t"] - target_t))
    if prior["v"] == 0:
        return None
    return (last["v"] - prior["v"]) / abs(prior["v"]) * 100.0


def _value_score_sopr(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_sopr(v, notes)


def _value_score_sth_sopr(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_sth_sopr(v)


def _value_score_mvrv(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_mvrv(v, notes)


def _value_score_sth_mvrv(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_sth_mvrv(v)


def _value_score_nupl(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    v = points[-1]["v"]
    return v, _score_nupl(v)


def _value_score_netflow(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    # "normalizar por p90 dos últimos 7 pontos" - literally the last 7
    # points of whatever series/interval Glassnode actually served (the
    # real lookback duration therefore depends on the interval).
    latest = points[-1]["v"]
    window = points[-7:]
    p90 = _percentile([abs(p["v"]) for p in window], 90.0)
    if not p90:
        return None, None
    # Positive netflow (inflow to exchanges) = RISK_OFF.
    return latest, _clamp(-latest / p90 * 80.0)


def _value_score_reserve_d1(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    pct = _delta_pct_over_seconds(points, 24 * 3600.0)
    if pct is None:
        return None, None
    return pct, _score_reserve_delta_pct(pct)


def _value_score_stables(points: list[dict], notes: list[str]) -> tuple[Optional[float], Optional[float]]:
    pct = _delta_pct_over_seconds(points, 7 * 24 * 3600.0)
    if pct is None:
        return None, None
    return points[-1]["v"], _score_stables_delta_pct(pct)


_VALUE_SCORE_FNS: dict[str, Callable[[list[dict], list[str]], tuple[Optional[float], Optional[float]]]] = {
    "sopr": _value_score_sopr,
    "sth_sopr": _value_score_sth_sopr,
    "mvrv": _value_score_mvrv,
    "sth_mvrv": _value_score_sth_mvrv,
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
        "profile": _active_profile(),
        "glassnode_score": 0.0,
        "glassnode_bias": "NEUTRAL",
        "glassnode_confidence": 0.0,
        "components": _empty_components(),
        "notes": notes,
    }


async def _fetch_component(
    client: GlassnodeClient, key: str, asset: str, notes: list[str], close_time: Optional[int]
) -> tuple[_ComponentResult, str]:
    interval_used = "1h"
    last_note: Optional[str] = None
    for path in _METRIC_PATHS[key]:
        result = await client.get_metric(path, asset, "1h")
        interval_used = result.interval
        points = _filter_up_to(result.points, close_time) if result.points else result.points
        if points:
            value, score = _VALUE_SCORE_FNS[key](points, notes)
            if value is not None and score is not None:
                return _ComponentResult(round(value, 6), round(score, 2), True), interval_used
            last_note = f"{key}: not enough history for delta yet"
            continue
        last_note = f"{key}: {result.note or 'no points up to closeTime'}"
    if last_note:
        notes.append(last_note)
    return _ComponentResult(None, None, False), interval_used


async def compute_glassnode_sentiment(
    symbol: str,
    client: Optional[GlassnodeClient] = None,
    close_time: Optional[int] = None,
) -> dict:
    """Builds the `glassnode` sibling block for the /signal payload.
    Never raises - any failure (no key, bad key, network, rate limit)
    degrades to has_key=false / avail=false components so the endpoint
    still returns 200.

    `close_time` (unix seconds) is optional and unused by /signal
    itself (which has no "alert" concept) - it exists so a caller with
    an actual alert timestamp (the alerts app) can pass it and get a
    lookahead-safe read (only points with t <= close_time are used)."""
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

    for key in COMPONENT_KEYS:
        comp, iv = await _fetch_component(client, key, asset, notes, close_time)
        components[key] = {"value": comp.value, "score": comp.score, "avail": comp.avail}
        if iv == "24h":
            interval_used = "24h"

    profile = _active_profile()
    weights = _WEIGHT_PROFILES[profile]
    weighted_sum = 0.0
    weight_total = 0.0
    for key in COMPONENT_KEYS:
        comp = components[key]
        if comp["avail"]:
            weighted_sum += weights[key] * comp["score"]
            weight_total += weights[key]

    glassnode_score = round(weighted_sum / weight_total, 2) if weight_total > 0 else 0.0
    available_count = sum(1 for k in COMPONENT_KEYS if components[k]["avail"])
    confidence = round(available_count / len(COMPONENT_KEYS) * 100.0, 1)
    bias = _bias_from_score(glassnode_score) if weight_total > 0 else "NEUTRAL"

    return {
        "has_key": True,
        "asof": int(time.time()),
        "asset_used": asset,
        "asset_direct": asset_direct,
        "interval": interval_used,
        "profile": profile,
        "glassnode_score": glassnode_score,
        "glassnode_bias": bias,
        "glassnode_confidence": confidence,
        "components": components,
        "notes": notes,
    }


def evaluate_glassnode_gate(
    components: dict,
    glassnode_score: float,
    glassnode_confidence: float,
    side: str,
    enabled: Optional[bool] = None,
) -> str:
    """Pure helper for the caller (the alerts app) that already knows
    the side (LONG/SHORT). Not called automatically from /signal.
    Gated by GLASSNODE_GATE (default off; when off, always "allow").
    Implements the asymmetric long/short rules from the briefing - the
    backtest tolerates short much better than long, so long has two
    independent ways to get blocked and short only one."""
    if enabled is None:
        enabled = os.environ.get("GLASSNODE_GATE", "off").lower() == "on"
    if not enabled:
        return "allow"

    side = side.upper()

    def val(key: str) -> Optional[float]:
        return components.get(key, {}).get("value")

    def score(key: str) -> Optional[float]:
        return components.get(key, {}).get("score")

    if side == "LONG":
        if glassnode_score <= -12:
            return "block"
        sopr_v, sth_mvrv_v, mvrv_v, netflow_score = val("sopr"), val("sth_mvrv"), val("mvrv"), score("exch_netflow")
        cond_profit_distribution = sopr_v is not None and sth_mvrv_v is not None and sopr_v > 1.05 and sth_mvrv_v > 1.2
        cond_euphoria = mvrv_v is not None and mvrv_v >= 2.4
        cond_netflow = netflow_score is not None and netflow_score <= -50
        if cond_profit_distribution or cond_euphoria or cond_netflow:
            return "block"
    elif side == "SHORT":
        if glassnode_score >= 28:
            return "block"
        sth_sopr_v, netflow_score = val("sth_sopr"), score("exch_netflow")
        if sth_sopr_v is not None and netflow_score is not None and sth_sopr_v < 0.97 and netflow_score >= 50:
            return "block"

    bias = _bias_from_score(glassnode_score)
    if bias == "NEUTRAL" and glassnode_confidence >= 50:
        return "reduce"
    return "allow"


_client_singleton: Optional[GlassnodeClient] = None


def _default_client() -> GlassnodeClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = GlassnodeClient()
    return _client_singleton
