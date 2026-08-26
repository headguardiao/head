import time

import pytest

from forge.engine.score_engine import SymbolMarketState
from forge.engine.sentiment_engine import COMPONENT_KEYS, compute_sentiment, evaluate_sentiment_gate
from forge.models import Liquidation, Side


class FakeSentimentClient:
    """Duck-typed stand-in for SentimentClient - every method returns
    canned data (or None to simulate a dead source)."""

    def __init__(self, *, dead=False):
        self.dead = dead
        now_ms = int(time.time() * 1000)
        self._funding_history = None if dead else [
            {"fundingTime": now_ms - i * 8 * 3600 * 1000, "fundingRate": str(0.0001 * (1 if i % 2 else -1))}
            for i in range(20, -1, -1)
        ] + [{"fundingTime": now_ms, "fundingRate": "0.001"}]  # latest spikes positive
        self._premium = None if dead else {"markPrice": "101.0", "indexPrice": "100.0"}
        self._global_ls = None if dead else [{"longShortRatio": "0.8"}]
        self._top_ls = None if dead else [{"longShortRatio": "2.5"}]
        self._taker = None if dead else {"15m": [{"buySellRatio": "1.2"}], "1h": [{"buySellRatio": "1.0"}]}
        self._oi_hist = None if dead else [{"sumOpenInterestValue": "1000000"}, {"sumOpenInterestValue": "1100000"}]
        self._klines = None if dead else [[0, "100", "0", "0", "0"], [0, "0", "0", "0", "105"]]
        self._fng = None if dead else {"data": [{"value": "20"}]}

    async def funding_rate_history(self, symbol, limit=21):
        return self._funding_history

    async def premium_index(self, symbol):
        return self._premium

    async def global_long_short_ratio(self, symbol, period="15m"):
        return self._global_ls

    async def top_long_short_position_ratio(self, symbol, period="15m"):
        return self._top_ls

    async def taker_long_short_ratio(self, symbol, period="15m"):
        return None if self.dead else self._taker[period]

    async def open_interest_hist(self, symbol, period="15m", limit=2):
        return self._oi_hist

    async def klines(self, symbol, interval="15m", limit=2):
        return self._klines

    async def fear_greed(self):
        return self._fng


@pytest.mark.asyncio
async def test_dead_sources_degrade_cleanly():
    client = FakeSentimentClient(dead=True)
    result = await compute_sentiment("BTCUSDT", client=client)

    assert set(result["components"].keys()) == set(COMPONENT_KEYS)
    assert all(c["avail"] is False for c in result["components"].values())
    assert result["sentiment_bias"] == "NEUTRAL"
    assert result["sentiment_confidence"] == 0.0
    assert result["btc_anchor"] == {"score": 0.0, "bias": "NEUTRAL"}


@pytest.mark.asyncio
async def test_full_sources_compute_a_score():
    client = FakeSentimentClient()
    state = SymbolMarketState("BTCUSDT")
    state.on_liquidation(Liquidation(exchange="bybit", symbol="BTCUSDT", side=Side.SELL, price=100.0, qty=1.0, timestamp=time.time()))
    result = await compute_sentiment("BTCUSDT", client=client, states={"BTCUSDT": state})

    assert all(c["avail"] for c in result["components"].values())
    assert result["sentiment_confidence"] == 100.0
    assert -100.0 <= result["sentiment_score"] <= 100.0
    assert result["components"]["whale_pos_ls"]["value"] == 2.5
    assert "whale crowded long" in result["notes"]


@pytest.mark.asyncio
async def test_fng_is_tracked_but_never_scored():
    client = FakeSentimentClient()
    baseline = await compute_sentiment("BTCUSDT", client=client)

    class ExtremeFngClient(FakeSentimentClient):
        async def fear_greed(self):
            return {"data": [{"value": "0"}]}  # extreme fear -> would swing the score hard if counted

    extreme = await compute_sentiment("BTCUSDT", client=ExtremeFngClient())

    assert baseline["sentiment_score"] == extreme["sentiment_score"]
    assert extreme["components"]["fng"]["avail"] is True
    assert extreme["components"]["fng"]["value"] == 0.0


@pytest.mark.asyncio
async def test_liq_side_reuses_existing_state_liquidations():
    client = FakeSentimentClient()
    state = SymbolMarketState("BTCUSDT")
    # Two longs liquidated (SELL closes a long) for one short (BUY closes a short).
    state.on_liquidation(Liquidation(exchange="bybit", symbol="BTCUSDT", side=Side.SELL, price=100.0, qty=2.0, timestamp=time.time()))
    state.on_liquidation(Liquidation(exchange="bybit", symbol="BTCUSDT", side=Side.BUY, price=100.0, qty=1.0, timestamp=time.time()))

    result = await compute_sentiment("BTCUSDT", client=client, states={"BTCUSDT": state})

    liq = result["components"]["liq_side"]
    assert liq["avail"] is True
    assert liq["value"] > 0  # more long notional liquidated than short
    assert liq["score"] < 0  # long-heavy liquidations -> RISK_OFF


@pytest.mark.asyncio
async def test_alt_symbol_gets_own_and_btc_anchor():
    client = FakeSentimentClient()
    result = await compute_sentiment("ETHUSDT", client=client)

    assert "btc_anchor" in result
    assert set(result["btc_anchor"].keys()) == {"score", "bias"}


def test_gate_off_by_default_always_allows():
    assert evaluate_sentiment_gate(-90, 10, "LONG", enabled=False) == "allow"


def test_gate_blocks_long_on_strong_risk_off():
    assert evaluate_sentiment_gate(-30, 80, "LONG", enabled=True) == "block"


def test_gate_blocks_short_on_strong_risk_on():
    assert evaluate_sentiment_gate(30, 80, "SHORT", enabled=True) == "block"


def test_gate_reduces_on_neutral_with_confidence():
    assert evaluate_sentiment_gate(0, 60, "LONG", enabled=True) == "reduce"


def test_gate_allows_when_block_threshold_not_met():
    # RISK_OFF (<=-15) but not extreme enough (|score|<25) to block, and
    # not NEUTRAL so the reduce rule doesn't apply either.
    assert evaluate_sentiment_gate(-20, 80, "LONG", enabled=True) == "allow"
