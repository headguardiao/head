import time

import pytest

from forge.engine.onchain_engine import COMPONENT_KEYS, compute_onchain, evaluate_onchain_gate


class FakeOnchainClient:
    def __init__(self, *, dead=False):
        self.dead = dead
        now = time.time()
        self._fees = None if dead else {"fastestFee": 20}
        self._mempool = None if dead else {"count": 5000}
        self._hashrate = None if dead else {
            "hashrates": [
                {"timestamp": now - 3 * 24 * 3600, "avgHashrate": 5e20},
                {"timestamp": now, "avgHashrate": 5.5e20},
            ]
        }
        self._tvl = None if dead else [
            {"date": now - 24 * 3600, "tvl": 1_000_000_000},
            {"date": now, "tvl": 1_050_000_000},
        ]
        self._stable_charts = None if dead else [
            {"date": now - 7 * 24 * 3600, "totalCirculating": {"peggedUSD": 100_000_000_000}},
            {"date": now, "totalCirculating": {"peggedUSD": 103_000_000_000}},
        ]
        self._stable_prices = None if dead else [
            {"symbol": "USDT", "price": 1.0005},
            {"symbol": "USDC", "price": 0.9998},
        ]
        self._gas = None if dead else 25.0

    async def btc_fees_recommended(self):
        return self._fees

    async def btc_mempool(self):
        return self._mempool

    async def btc_hashrate(self, period="3d"):
        return self._hashrate

    async def historical_chain_tvl(self, chain):
        return self._tvl

    async def stablecoin_charts_all(self):
        return self._stable_charts

    async def stablecoin_prices(self):
        return self._stable_prices

    async def eth_gas_price_gwei(self):
        return self._gas


@pytest.mark.asyncio
async def test_dead_sources_degrade_cleanly():
    client = FakeOnchainClient(dead=True)
    result = await compute_onchain("BTCUSDT", client=client)

    assert set(result["components"].keys()) == set(COMPONENT_KEYS)
    assert all(c["avail"] is False for c in result["components"].values())
    assert result["onchain_bias"] == "NEUTRAL"
    assert result["onchain_confidence"] == 0.0
    assert result["peg_stressed"] is False


@pytest.mark.asyncio
async def test_btc_only_uses_global_layer():
    client = FakeOnchainClient()
    result = await compute_onchain("BTCUSDT", client=client)

    assert result["chain_used"] is None
    assert result["components"]["chain_tvl_1d"]["avail"] is False
    assert result["components"]["eth_gas"]["avail"] is False
    assert result["components"]["btc_fee"]["avail"] is True
    assert result["components"]["btc_mempool"]["avail"] is True
    assert result["components"]["btc_hashrate"]["avail"] is True
    assert -100.0 <= result["onchain_score"] <= 100.0


@pytest.mark.asyncio
async def test_eth_symbol_gets_chain_and_gas_components():
    client = FakeOnchainClient()
    result = await compute_onchain("ETHUSDT", client=client)

    assert result["chain_used"] == "Ethereum"
    assert result["components"]["chain_tvl_1d"]["avail"] is True
    assert result["components"]["eth_gas"]["avail"] is True


@pytest.mark.asyncio
async def test_peg_stress_forces_risk_off():
    class StressedClient(FakeOnchainClient):
        async def stablecoin_prices(self):
            return [{"symbol": "USDT", "price": 0.98}, {"symbol": "USDC", "price": 1.0}]

    result = await compute_onchain("BTCUSDT", client=StressedClient())

    assert result["peg_stressed"] is True
    assert result["onchain_bias"] == "RISK_OFF"
    assert "stable peg stress" in result["notes"]


def test_gate_off_by_default_always_allows():
    assert evaluate_onchain_gate("RISK_OFF", True, 10, "LONG", enabled=False) == "allow"


def test_gate_blocks_long_on_peg_stress():
    assert evaluate_onchain_gate("RISK_OFF", True, 10, "LONG", enabled=True) == "block"


def test_gate_does_not_block_short_on_peg_stress():
    assert evaluate_onchain_gate("RISK_OFF", True, 10, "SHORT", enabled=True) == "allow"


def test_gate_reduces_on_neutral_with_confidence():
    assert evaluate_onchain_gate("NEUTRAL", False, 60, "LONG", enabled=True) == "reduce"
