from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

from forge.engine.sentiment_client import SentimentClient
from forge.engine.score_engine import SymbolMarketState
from forge.models import Side

# ADD-ONLY module (Camada C do briefing). Never imported by
# score_engine.py's compute() path; never touches liquidity_score,
# the PDF §7 weights, the 1.15x wall bias threshold, or
# confidence=exchanges/3. This is a sibling data source consumed
# through GET /sentiment/{symbol} and an optional `sentiment` key on
# /signal/{symbol}.

# Note: the spec lists "ticker 24h spot" among the Camada C sources but
# never maps it into any of the 9 named components/formulas below - it
# stays available on SentimentClient (client.ticker_24h_spot) for
# future/dashboard use, deliberately not wired into a score here to
# avoid inventing an unspecified formula.

COMPONENT_KEYS = [
    "funding_z",
    "basis_bps",
    "retail_ls",
    "whale_pos_ls",
    "taker_15m",
    "taker_shift",
    "oi_price_agree",
    "liq_side",
    "fng",
]

# fng is informational only ("só dashboard; peso 0 no 30m") - it's a
# tracked component (counts toward sentiment_confidence) but is never
# part of the sentiment_score average.
SCORED_COMPONENT_KEYS = [k for k in COMPONENT_KEYS if k != "fng"]

BIAS_THRESHOLD = 15.0  # same scale/threshold convention as the Glassnode add-on

# Heuristic calibration constant - oi_price_agree isn't given an exact
# scale in the spec ("mesmo sinal = a favor, sinais opostos = contra"),
# only the sign rule. Tune once real magnitudes are observed.
_OI_PRICE_AGREE_SCALE = 15.0


def _clamp(value: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _component(value: Optional[float], score: Optional[float]) -> dict:
    avail = value is not None and score is not None
    return {
        "value": round(value, 6) if avail else None,
        "score": round(score, 2) if avail else None,
        "avail": avail,
    }


async def _funding_z(client: SentimentClient, symbol: str) -> dict:
    history = await client.funding_rate_history(symbol, limit=21)
    if not history:
        return _component(None, None)
    try:
        rates = [float(r["fundingRate"]) for r in history]
    except (KeyError, TypeError, ValueError):
        return _component(None, None)
    if len(rates) < 2:
        return _component(None, None)
    mean = sum(rates) / len(rates)
    variance = sum((r - mean) ** 2 for r in rates) / len(rates)
    stdev = variance ** 0.5
    latest = rates[-1]
    z = 0.0 if stdev == 0 else (latest - mean) / stdev
    # funding alto (positivo) e fora do normal = mercado lotado de long -> RISK_OFF.
    return _component(z, _clamp(-z * 40.0))


async def _basis_bps(client: SentimentClient, symbol: str) -> dict:
    data = await client.premium_index(symbol)
    if not data:
        return _component(None, None)
    try:
        mark = float(data["markPrice"])
        index = float(data["indexPrice"])
    except (KeyError, TypeError, ValueError):
        return _component(None, None)
    if index == 0:
        return _component(None, None)
    basis_bps = (mark - index) / index * 10000.0
    # premium (futuro acima do índice) = alavancagem otimista -> RISK_OFF.
    return _component(basis_bps, _clamp(-basis_bps * 2.0))


async def _retail_ls(client: SentimentClient, symbol: str) -> dict:
    data = await client.global_long_short_ratio(symbol)
    if not data:
        return _component(None, None)
    try:
        ratio = float(data[-1]["longShortRatio"])
    except (KeyError, IndexError, TypeError, ValueError):
        return _component(None, None)
    return _component(ratio, _clamp((1.0 - ratio) * 80.0))


async def _whale_pos_ls(client: SentimentClient, symbol: str, notes: list[str]) -> dict:
    data = await client.top_long_short_position_ratio(symbol)
    if not data:
        return _component(None, None)
    try:
        ratio = float(data[-1]["longShortRatio"])
    except (KeyError, IndexError, TypeError, ValueError):
        return _component(None, None)
    if ratio > 2.0:
        notes.append("whale crowded long")
    return _component(ratio, _clamp((1.0 - ratio) * 60.0))


async def _taker_ratio(client: SentimentClient, symbol: str, period: str) -> Optional[float]:
    data = await client.taker_long_short_ratio(symbol, period)
    if not data:
        return None
    try:
        return float(data[-1]["buySellRatio"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


async def _oi_price_agree(client: SentimentClient, symbol: str) -> dict:
    oi_hist, candles = await client.open_interest_hist(symbol), await client.klines(symbol)
    if not oi_hist or not candles or len(oi_hist) < 2 or len(candles) < 2:
        return _component(None, None)
    try:
        oi_start = float(oi_hist[0]["sumOpenInterestValue"])
        oi_end = float(oi_hist[-1]["sumOpenInterestValue"])
        price_start = float(candles[0][1])  # open of the oldest candle
        price_end = float(candles[-1][4])  # close of the newest candle
    except (KeyError, IndexError, TypeError, ValueError):
        return _component(None, None)
    if oi_start == 0 or price_start == 0:
        return _component(None, None)

    oi_change_pct = (oi_end - oi_start) / oi_start * 100.0
    price_change_pct = (price_end - price_start) / price_start * 100.0
    magnitude = _clamp((abs(oi_change_pct) + abs(price_change_pct)) * _OI_PRICE_AGREE_SCALE, 0.0, 100.0)
    agree = (oi_change_pct > 0) == (price_change_pct > 0)
    same_direction = oi_change_pct != 0 and price_change_pct != 0
    score = magnitude if (agree and same_direction) else -magnitude
    return _component(oi_change_pct, score)


def _liq_side(state: Optional[SymbolMarketState]) -> dict:
    if state is None:
        return _component(None, None)
    liquidations = state.recent_liquidations
    if not liquidations:
        return _component(None, None)
    # Liquidation.side is the side of the FORCED order (as ingested from
    # Bybit's allLiquidation feed: "S" is the closing order's side, the
    # opposite of the position that got liquidated) - SELL closes a
    # long, BUY closes a short.
    long_notional = sum(l.price * l.qty for l in liquidations if l.side == Side.SELL)
    short_notional = sum(l.price * l.qty for l in liquidations if l.side == Side.BUY)
    total = long_notional + short_notional
    if total == 0:
        return _component(None, None)
    raw = (long_notional - short_notional) / total
    # raw > 0 = mais notional de LONG liquidado = RISK_OFF -> score negativo.
    return _component(raw, _clamp(-raw * 100.0))


async def _fng(client: SentimentClient) -> dict:
    data = await client.fear_greed()
    if not data:
        return _component(None, None)
    try:
        raw = float(data["data"][0]["value"])
    except (KeyError, IndexError, TypeError, ValueError):
        return _component(None, None)
    return _component(raw, _clamp((50.0 - raw) * 2.0))


def _bias_from_score(score: float) -> str:
    if score >= BIAS_THRESHOLD:
        return "RISK_ON"
    if score <= -BIAS_THRESHOLD:
        return "RISK_OFF"
    return "NEUTRAL"


async def _compute_one(symbol: str, client: SentimentClient, state: Optional[SymbolMarketState]) -> tuple[dict, list[str]]:
    notes: list[str] = []

    funding_z_task = _funding_z(client, symbol)
    basis_bps_task = _basis_bps(client, symbol)
    retail_ls_task = _retail_ls(client, symbol)
    whale_pos_ls_task = _whale_pos_ls(client, symbol, notes)
    taker_15m_ratio_task = _taker_ratio(client, symbol, "15m")
    taker_1h_ratio_task = _taker_ratio(client, symbol, "1h")
    oi_price_agree_task = _oi_price_agree(client, symbol)
    fng_task = _fng(client)

    (
        funding_z,
        basis_bps,
        retail_ls,
        whale_pos_ls,
        taker_15m_ratio,
        taker_1h_ratio,
        oi_price_agree,
        fng,
    ) = await asyncio.gather(
        funding_z_task,
        basis_bps_task,
        retail_ls_task,
        whale_pos_ls_task,
        taker_15m_ratio_task,
        taker_1h_ratio_task,
        oi_price_agree_task,
        fng_task,
    )

    if taker_15m_ratio is None:
        taker_15m = _component(None, None)
    else:
        # fluxo de agressão a favor do preço, NÃO contrarian.
        taker_15m = _component(taker_15m_ratio, _clamp((taker_15m_ratio - 1.0) * 100.0))

    if taker_15m_ratio is None or taker_1h_ratio is None:
        taker_shift = _component(None, None)
    else:
        shift = taker_15m_ratio - taker_1h_ratio
        taker_shift = _component(shift, _clamp(shift * 150.0))

    liq_side = _liq_side(state)

    components = {
        "funding_z": funding_z,
        "basis_bps": basis_bps,
        "retail_ls": retail_ls,
        "whale_pos_ls": whale_pos_ls,
        "taker_15m": taker_15m,
        "taker_shift": taker_shift,
        "oi_price_agree": oi_price_agree,
        "liq_side": liq_side,
        "fng": fng,
    }

    scores = [components[k]["score"] for k in SCORED_COMPONENT_KEYS if components[k]["avail"]]
    sentiment_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    available_count = sum(1 for k in COMPONENT_KEYS if components[k]["avail"])
    sentiment_confidence = round(available_count / len(COMPONENT_KEYS) * 100.0, 1)
    sentiment_bias = _bias_from_score(sentiment_score) if scores else "NEUTRAL"

    result = {
        "symbol": symbol,
        "asof": int(time.time()),
        "sentiment_score": sentiment_score,
        "sentiment_bias": sentiment_bias,
        "sentiment_confidence": sentiment_confidence,
        "components": components,
        "notes": notes,
    }
    return result, notes


async def compute_sentiment(
    symbol: str,
    client: Optional[SentimentClient] = None,
    states: Optional[dict[str, SymbolMarketState]] = None,
) -> dict:
    """Builds the Camada C sentiment payload. Never raises - any dead
    source resolves to avail=false for that one component, never a
    500. `states` (the same dict forge/app.py already builds) is
    optional and only used to reuse already-ingested liquidations for
    liq_side - never to recompute anything from score_engine.py."""
    client = client or _default_client()
    states = states or {}

    result, _ = await _compute_one(symbol, client, states.get(symbol))

    if symbol.upper() == "BTCUSDT":
        result["btc_anchor"] = {"score": result["sentiment_score"], "bias": result["sentiment_bias"]}
        return result

    btc_result, _ = await _compute_one("BTCUSDT", client, states.get("BTCUSDT"))
    result["btc_anchor"] = {"score": btc_result["sentiment_score"], "bias": btc_result["sentiment_bias"]}
    if {result["sentiment_bias"], btc_result["sentiment_bias"]} == {"RISK_ON", "RISK_OFF"}:
        result["notes"].append(
            f"{symbol} {result['sentiment_bias']} but BTC anchor {btc_result['sentiment_bias']}"
        )
    return result


def evaluate_sentiment_gate(
    sentiment_score: float,
    sentiment_confidence: float,
    side: str,
    enabled: Optional[bool] = None,
) -> str:
    """Pure helper for the caller (the alerts app) that already knows
    which side (LONG/SHORT) it wants to take. Not called automatically
    from /sentiment or /signal - this module has no "side" input of
    its own. Gated by FORGE_SENTIMENT_GATE (default off); when off,
    always "allow" regardless of the numbers, so nothing changes until
    the flag is explicitly turned on."""
    if enabled is None:
        enabled = os.environ.get("FORGE_SENTIMENT_GATE", "off").lower() == "on"
    if not enabled:
        return "allow"

    bias = _bias_from_score(sentiment_score)
    side = side.upper()
    if side == "LONG" and bias == "RISK_OFF" and abs(sentiment_score) >= 25:
        return "block"
    if side == "SHORT" and bias == "RISK_ON" and abs(sentiment_score) >= 25:
        return "block"
    if bias == "NEUTRAL" and sentiment_confidence >= 50:
        return "reduce"
    return "allow"


_client_singleton: Optional[SentimentClient] = None


def _default_client() -> SentimentClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = SentimentClient()
    return _client_singleton
