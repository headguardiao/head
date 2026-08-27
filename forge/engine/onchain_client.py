from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

MEMPOOL_BASE = "https://mempool.space/api"
LLAMA_BASE = "https://api.llama.fi"
STABLECOINS_BASE = "https://stablecoins.llama.fi"
# Cloudflare's public no-key Ethereum RPC gateway - used only for
# eth_gasPrice (best-effort; spec explicitly forbids requesting an
# Etherscan key).
ETH_RPC_URL = "https://cloudflare-eth.com"

REQUEST_TIMEOUT_SECONDS = 3.0
CACHE_TTL_SECONDS = 60.0


class OnchainClient:
    """Public (no API key) client for mempool.space + DefiLlama, used
    by the Camada D on-chain layer. Every source is independent and
    best-effort: a dead/blocked (e.g. 403) source resolves to `None`,
    never an exception, so one broken endpoint can't take the whole
    `onchain` block down. Responses cached 60s."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: dict[tuple, tuple[float, Any]] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _get_json(self, url: str) -> Optional[Any]:
        cached = self._cache.get(url)
        if cached is not None and time.time() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        session = await self._get_session()
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
            ) as resp:
                if resp.status != 200:
                    logger.info("onchain source %s -> http %s", url, resp.status)
                    self._cache[url] = (time.time(), None)
                    return None
                data = await resp.json(content_type=None)
        except Exception as exc:
            logger.info("onchain source %s failed: %s", url, exc)
            self._cache[url] = (time.time(), None)
            return None

        self._cache[url] = (time.time(), data)
        return data

    # ---- Bitcoin / global -------------------------------------------
    async def btc_fees_recommended(self) -> Optional[dict]:
        return await self._get_json(f"{MEMPOOL_BASE}/v1/fees/recommended")

    async def btc_mempool(self) -> Optional[dict]:
        return await self._get_json(f"{MEMPOOL_BASE}/mempool")

    async def btc_hashrate(self, period: str = "3d") -> Optional[dict]:
        return await self._get_json(f"{MEMPOOL_BASE}/v1/mining/hashrate/{period}")

    # ---- DefiLlama chains / TVL --------------------------------------
    async def historical_chain_tvl(self, chain: str) -> Optional[list]:
        return await self._get_json(f"{LLAMA_BASE}/v2/historicalChainTvl/{chain}")

    # ---- Stablecoins --------------------------------------------------
    async def stablecoin_charts_all(self) -> Optional[list]:
        return await self._get_json(f"{STABLECOINS_BASE}/stablecoincharts/all")

    async def stablecoin_prices(self) -> Optional[list]:
        return await self._get_json(f"{STABLECOINS_BASE}/stablecoinprices")

    # ---- ETH gas (best-effort, no key) --------------------------------
    async def eth_gas_price_gwei(self) -> Optional[float]:
        session = await self._get_session()
        cache_key = "eth_gasPrice"
        cached = self._cache.get(cache_key)
        if cached is not None and time.time() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        payload = {"jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1}
        try:
            async with session.post(
                ETH_RPC_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    self._cache[cache_key] = (time.time(), None)
                    return None
                data = await resp.json(content_type=None)
        except Exception as exc:
            logger.info("eth gas price request failed: %s", exc)
            self._cache[cache_key] = (time.time(), None)
            return None

        result_hex = data.get("result") if isinstance(data, dict) else None
        if not result_hex:
            self._cache[cache_key] = (time.time(), None)
            return None
        try:
            gwei = int(result_hex, 16) / 1e9
        except (TypeError, ValueError):
            self._cache[cache_key] = (time.time(), None)
            return None
        self._cache[cache_key] = (time.time(), gwei)
        return gwei
