from __future__ import annotations

import logging
import time
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Same futures host the exchange adapters already use successfully
# (forge/adapters/binance.py) - avoid fapi.binance.com only if an
# environment 451s it, in which case switch both here and there.
FUTURES_BASE = "https://fapi.binance.com"
SPOT_BASE = "https://api.binance.com"
FNG_URL = "https://api.alternative.me/fng/"

REQUEST_TIMEOUT_SECONDS = 2.5
CACHE_TTL_SECONDS = 25.0


class SentimentClient:
    """Public (no API key) client for the Binance derivatives endpoints
    and Fear & Greed used by the Camada C sentiment layer. Every source
    is independent: a dead/slow source resolves to `None` for that one
    call, never an exception, so one broken endpoint can't take the
    whole /sentiment response down (spec: "fonte morta = null, nunca
    500"). Responses are cached 20-30s per (path, params)."""

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

    async def _get_json(self, base: str, path: str, params: dict) -> Optional[Any]:
        cache_key = (base, path, tuple(sorted(params.items())))
        cached = self._cache.get(cache_key)
        if cached is not None and time.time() - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]

        session = await self._get_session()
        try:
            async with session.get(
                f"{base}{path}",
                params=params,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    logger.info("sentiment source %s%s -> http %s", base, path, resp.status)
                    self._cache[cache_key] = (time.time(), None)
                    return None
                data = await resp.json()
        except Exception as exc:
            logger.info("sentiment source %s%s failed: %s", base, path, exc)
            self._cache[cache_key] = (time.time(), None)
            return None

        self._cache[cache_key] = (time.time(), data)
        return data

    # ---- individual sources ------------------------------------------
    async def premium_index(self, symbol: str) -> Optional[dict]:
        return await self._get_json(FUTURES_BASE, "/fapi/v1/premiumIndex", {"symbol": symbol})

    async def funding_rate_history(self, symbol: str, limit: int = 21) -> Optional[list]:
        return await self._get_json(FUTURES_BASE, "/fapi/v1/fundingRate", {"symbol": symbol, "limit": limit})

    async def global_long_short_ratio(self, symbol: str, period: str = "15m") -> Optional[list]:
        return await self._get_json(
            FUTURES_BASE, "/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": period, "limit": 1}
        )

    async def top_long_short_position_ratio(self, symbol: str, period: str = "15m") -> Optional[list]:
        return await self._get_json(
            FUTURES_BASE, "/futures/data/topLongShortPositionRatio", {"symbol": symbol, "period": period, "limit": 1}
        )

    async def taker_long_short_ratio(self, symbol: str, period: str) -> Optional[list]:
        return await self._get_json(
            FUTURES_BASE, "/futures/data/takerlongshortRatio", {"symbol": symbol, "period": period, "limit": 1}
        )

    async def open_interest_hist(self, symbol: str, period: str = "15m", limit: int = 2) -> Optional[list]:
        return await self._get_json(
            FUTURES_BASE, "/futures/data/openInterestHist", {"symbol": symbol, "period": period, "limit": limit}
        )

    async def klines(self, symbol: str, interval: str = "15m", limit: int = 2) -> Optional[list]:
        # Not in the spec's source list verbatim, but needed to pair
        # openInterestHist with a comparable price change for
        # oi_price_agree - same public futures host, no key.
        return await self._get_json(
            FUTURES_BASE, "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )

    async def ticker_24h_spot(self, symbol: str) -> Optional[dict]:
        return await self._get_json(SPOT_BASE, "/api/v3/ticker/24hr", {"symbol": symbol})

    async def fear_greed(self) -> Optional[list]:
        return await self._get_json(FNG_URL, "", {"limit": 2})
