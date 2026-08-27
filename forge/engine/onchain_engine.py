from __future__ import annotations

import os
import time
from typing import Optional

from forge.engine.onchain_client import OnchainClient

# ADD-ONLY module (Camada D do briefing). Objeto irmão `onchain` em
# /signal/{symbol}. Sem Glassnode aqui (isso é Camada E, em
# glassnode_sentiment.py) - só mempool.space + DefiLlama, sem chave.
# Nunca toca liquidity_score, os pesos PDF §7, o bias de paredes ou
# confidence=exchanges/3.

# Alt -> chain DefiLlama. BTC e "meme coins" sem chain própria de TVL
# relevante usam só a camada global (btc_fee/btc_mempool/btc_hashrate/
# stables_7d/peg_stress) - chain_tvl_1d e eth_gas ficam avail=false.
_CHAIN_MAP = {
    "ETHUSDT": "Ethereum",
    "ARBUSDT": "Arbitrum",
    "OPUSDT": "Optimism",
    "SOLUSDT": "Solana",
    "SUIUSDT": "Sui",
    "AVAXUSDT": "Avalanche",
    "BNBUSDT": "BSC",
}
COMPONENT_KEYS = [
    "stables_7d",
    "chain_tvl_1d",
    "btc_fee",
    "btc_mempool",
    "peg_stress",
    "eth_gas",
    "btc_hashrate",
]

# Weights from the briefing's "Pesos 30m" table for Camada D; sum to
# 1.0. Renormalized over whichever components are avail (chain_tvl_1d
# and eth_gas are structurally unavailable for BTC/meme symbols).
_WEIGHTS_30M = {
    "stables_7d": 0.22,
    "chain_tvl_1d": 0.18,
    "btc_fee": 0.16,
    "btc_mempool": 0.14,
    "peg_stress": 0.14,
    "eth_gas": 0.10,
    "btc_hashrate": 0.06,
}

BIAS_THRESHOLD = 15.0
PEG_STRESS_BPS_THRESHOLD = 50.0

# Heuristic calibration constants - the briefing gives weights and the
# peg-stress override rule but no exact per-component formula for
# Camada D (unlike Camada C). These are documented, tunable directional
# leans, not a validated model:
# - btc_fee / btc_mempool / eth_gas: congestion proxies. Treated as a
#   caution signal (RISK_OFF lean) when elevated - heavy on-chain
#   activity/backlog reads as urgency/stress rather than calm
#   accumulation. Tune the baselines once real magnitudes are observed.
_BTC_FEE_BASELINE_SAT_VB = 20.0
_BTC_FEE_SCALE = 3.0
_BTC_MEMPOOL_BASELINE_COUNT = 5000.0
_BTC_MEMPOOL_SCALE = 0.02
_ETH_GAS_BASELINE_GWEI = 30.0
_ETH_GAS_SCALE = 2.0
_CHAIN_TVL_SCALE = 15.0
_STABLES_SCALE = 10.0
_HASHRATE_SCALE = 20.0
_PEG_STRESS_SCALE = 2.0


def _clamp(value: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _component(value: Optional[float], score: Optional[float]) -> dict:
    avail = value is not None and score is not None
    return {
        "value": round(value, 6) if avail else None,
        "score": round(score, 2) if avail else None,
        "avail": avail,
    }


def _pct_change_over_seconds(series: list[tuple[float, float]], window_seconds: float) -> Optional[float]:
    """series: list of (timestamp, value), any order. % change between
    the last point and whichever prior point is closest to
    `window_seconds` before it."""
    if len(series) < 2:
        return None
    series = sorted(series, key=lambda p: p[0])
    last_t, last_v = series[-1]
    target_t = last_t - window_seconds
    prior_t, prior_v = min(series[:-1], key=lambda p: abs(p[0] - target_t))
    if prior_v == 0:
        return None
    return (last_v - prior_v) / abs(prior_v) * 100.0


def _resolve_chain(symbol: str) -> Optional[str]:
    return _CHAIN_MAP.get(symbol.upper())


async def _btc_fee(client: OnchainClient) -> dict:
    data = await client.btc_fees_recommended()
    if not data:
        return _component(None, None)
    fee = data.get("fastestFee")
    if fee is None:
        return _component(None, None)
    fee = float(fee)
    return _component(fee, _clamp(-(fee - _BTC_FEE_BASELINE_SAT_VB) * _BTC_FEE_SCALE))


async def _btc_mempool(client: OnchainClient) -> dict:
    data = await client.btc_mempool()
    if not data:
        return _component(None, None)
    count = data.get("count")
    if count is None:
        return _component(None, None)
    count = float(count)
    return _component(count, _clamp(-(count - _BTC_MEMPOOL_BASELINE_COUNT) * _BTC_MEMPOOL_SCALE))


async def _btc_hashrate(client: OnchainClient) -> dict:
    data = await client.btc_hashrate("3d")
    if not data or not isinstance(data.get("hashrates"), list):
        return _component(None, None)
    points = [
        (float(p["timestamp"]), float(p["avgHashrate"]))
        for p in data["hashrates"]
        if "timestamp" in p and "avgHashrate" in p
    ]
    change_pct = _pct_change_over_seconds(points, 3 * 24 * 3600.0)
    if change_pct is None:
        return _component(None, None)
    # Rising hashrate = more security/commitment behind the network -> RISK_ON.
    return _component(change_pct, _clamp(change_pct * _HASHRATE_SCALE))


async def _chain_tvl_1d(client: OnchainClient, symbol: str) -> dict:
    chain = _resolve_chain(symbol)
    if chain is None:
        return _component(None, None)
    data = await client.historical_chain_tvl(chain)
    if not data or not isinstance(data, list):
        return _component(None, None)
    points = [(float(p["date"]), float(p["tvl"])) for p in data if "date" in p and "tvl" in p]
    change_pct = _pct_change_over_seconds(points, 24 * 3600.0)
    if change_pct is None:
        return _component(None, None)
    # Rising TVL = capital flowing into the chain -> RISK_ON.
    return _component(change_pct, _clamp(change_pct * _CHAIN_TVL_SCALE))


async def _stables_7d(client: OnchainClient) -> dict:
    data = await client.stablecoin_charts_all()
    if not data or not isinstance(data, list):
        return _component(None, None)
    points = []
    for p in data:
        total = p.get("totalCirculating", {})
        v = total.get("peggedUSD") if isinstance(total, dict) else None
        if "date" in p and v is not None:
            points.append((float(p["date"]), float(v)))
    change_pct = _pct_change_over_seconds(points, 7 * 24 * 3600.0)
    if change_pct is None:
        return _component(None, None)
    # Growing aggregate stablecoin supply = more on-chain dry powder -> RISK_ON.
    return _component(change_pct, _clamp(change_pct * _STABLES_SCALE))


async def _peg_stress(client: OnchainClient) -> tuple[dict, bool]:
    """Returns (component, is_stressed)."""
    data = await client.stablecoin_prices()
    if not data or not isinstance(data, list):
        return _component(None, None), False

    worst_bps = None
    for entry in data:
        symbol = str(entry.get("symbol", "")).upper()
        price = entry.get("price")
        if symbol not in ("USDT", "USDC") or price is None:
            continue
        dev_bps = (float(price) - 1.0) * 10000.0
        if worst_bps is None or abs(dev_bps) > abs(worst_bps):
            worst_bps = dev_bps

    if worst_bps is None:
        return _component(None, None), False

    is_stressed = abs(worst_bps) > PEG_STRESS_BPS_THRESHOLD
    score = _clamp(-abs(worst_bps) * _PEG_STRESS_SCALE)
    return _component(worst_bps, score), is_stressed


async def _eth_gas(client: OnchainClient) -> dict:
    # Caller (compute_onchain) only invokes this for symbols that
    # resolved to a chain - eth_gas isn't computed for BTC/meme (global
    # only) symbols, where it stays avail=false by construction.
    gwei = await client.eth_gas_price_gwei()
    if gwei is None:
        return _component(None, None)
    return _component(gwei, _clamp(-(gwei - _ETH_GAS_BASELINE_GWEI) * _ETH_GAS_SCALE))


def _bias_from_score(score: float) -> str:
    if score >= BIAS_THRESHOLD:
        return "RISK_ON"
    if score <= -BIAS_THRESHOLD:
        return "RISK_OFF"
    return "NEUTRAL"


async def compute_onchain(symbol: str, client: Optional[OnchainClient] = None) -> dict:
    """Builds the Camada D `onchain` sibling block. Never raises - any
    dead/blocked source (mempool.space, DefiLlama, the public ETH RPC)
    resolves to avail=false for that component, never a 500."""
    client = client or _default_client()
    notes: list[str] = []
    symbol_u = symbol.upper()
    # BTC and "meme" symbols (DOGE/PEPE/BONK/...) simply have no entry
    # in _CHAIN_MAP - they use only the global components (fee/mempool/
    # hashrate/stables/peg), per the briefing.
    is_global_only = _resolve_chain(symbol_u) is None

    peg_component, peg_stressed = await _peg_stress(client)
    components = {
        "stables_7d": await _stables_7d(client),
        "chain_tvl_1d": _component(None, None) if is_global_only else await _chain_tvl_1d(client, symbol_u),
        "btc_fee": await _btc_fee(client),
        "btc_mempool": await _btc_mempool(client),
        "peg_stress": peg_component,
        "eth_gas": _component(None, None) if is_global_only else await _eth_gas(client),
        "btc_hashrate": await _btc_hashrate(client),
    }

    if peg_stressed:
        notes.append("stable peg stress")

    weighted_sum = 0.0
    weight_total = 0.0
    for key in COMPONENT_KEYS:
        comp = components[key]
        if comp["avail"]:
            weighted_sum += _WEIGHTS_30M[key] * comp["score"]
            weight_total += _WEIGHTS_30M[key]

    onchain_score = round(weighted_sum / weight_total, 2) if weight_total > 0 else 0.0
    available_count = sum(1 for k in COMPONENT_KEYS if components[k]["avail"])
    onchain_confidence = round(available_count / len(COMPONENT_KEYS) * 100.0, 1)

    if weight_total <= 0:
        onchain_bias = "NEUTRAL"
    elif peg_stressed:
        onchain_bias = "RISK_OFF"  # spec: peg stress forces RISK_OFF regardless of the aggregate.
    else:
        onchain_bias = _bias_from_score(onchain_score)

    return {
        "symbol": symbol_u,
        "asof": int(time.time()),
        "chain_used": _resolve_chain(symbol_u),
        "onchain_score": onchain_score,
        "onchain_bias": onchain_bias,
        "onchain_confidence": onchain_confidence,
        "peg_stressed": peg_stressed,
        "components": components,
        "notes": notes,
    }


def evaluate_onchain_gate(
    onchain_bias: str,
    peg_stressed: bool,
    confidence: float,
    side: str,
    enabled: Optional[bool] = None,
) -> str:
    """Pure helper for the caller (the alerts app) that already knows
    the side (LONG/SHORT). Not called automatically from /signal - this
    module has no "side" input of its own. Gated by FORGE_ONCHAIN_GATE
    (default off); when off, always "allow"."""
    if enabled is None:
        enabled = os.environ.get("FORGE_ONCHAIN_GATE", "off").lower() == "on"
    if not enabled:
        return "allow"

    side = side.upper()
    if peg_stressed and side == "LONG":  # spec: "Peg stress -> block LONG"
        return "block"
    if onchain_bias == "NEUTRAL" and confidence >= 50:
        return "reduce"
    return "allow"


_client_singleton: Optional[OnchainClient] = None


def _default_client() -> OnchainClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = OnchainClient()
    return _client_singleton
