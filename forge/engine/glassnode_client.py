from __future__ import annotations

import logging
import os
import time
from typing import NamedTuple, Optional

import aiohttp

logger = logging.getLogger(__name__)

BASE_URL = "https://api.glassnode.com"
CACHE_TTL_SECONDS = 10 * 60
KEY_CHECK_CACHE_SECONDS = 24 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 4.0
KEY_CHECK_PATH = "/v1/metadata/metric"
KEY_CHECK_PARAMS = {"path": "/indicators/sopr"}


class MetricResult(NamedTuple):
    points: Optional[list[dict]]
    interval: str
    note: Optional[str]


class GlassnodeClient:
    """Thin cached client for the Glassnode metrics API.

    This is an add-on sentiment data source only - nothing in here is
    consumed by the core LIQUIDITY_SCORE pipeline. It must never raise
    out of a request path; every failure mode (missing key, 401/403,
    429, network error) resolves to a `MetricResult` with `points=None`
    and a short machine-readable `note`, so callers can degrade to
    avail=false instead of breaking the /signal endpoint.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else os.environ.get("GLASSNODE_API_KEY", "")
        self._session: Optional[aiohttp.ClientSession] = None
        # (path, asset, interval) -> (fetched_at, points or None)
        self._cache: dict[tuple[str, str, str], tuple[float, Optional[list[dict]]]] = {}
        self._key_valid: Optional[bool] = None
        self._key_checked_at: float = 0.0

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def ensure_key_valid(self) -> bool:
        """One-shot (cached 24h) check that the key works, via the
        cheapest possible call (metric metadata, not a data series).
        Never raises - a network failure here just means "not
        confirmed yet", which callers treat as module-off for the
        cycle rather than a hard error."""
        if not self.has_key:
            self._key_valid = False
            return False

        now = time.time()
        if self._key_valid is not None and now - self._key_checked_at < KEY_CHECK_CACHE_SECONDS:
            return self._key_valid

        session = await self._get_session()
        try:
            async with session.get(
                f"{BASE_URL}{KEY_CHECK_PATH}",
                params=KEY_CHECK_PARAMS,
                headers={"X-Api-Key": self.api_key},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as resp:
                self._key_valid = resp.status == 200
        except Exception:
            logger.warning("glassnode key check failed (network) - staying off this cycle")
            self._key_checked_at = now
            return False

        self._key_checked_at = now
        if not self._key_valid:
            logger.warning("glassnode unauthorized - on-chain sentiment disabled")
        return self._key_valid

    async def get_metric(self, path: str, asset: str, interval: str = "1h") -> MetricResult:
        """Fetch one Glassnode metric series, cached 10 minutes per
        (path, asset, interval). Assets shared across symbols (e.g. the
        BTC anchor layer used for every alt) naturally share this cache."""
        if not self.has_key:
            return MetricResult(None, interval, "glassnode no api key")

        cache_key = (path, asset, interval)
        cached = self._cache.get(cache_key)
        if cached is not None and time.time() - cached[0] < CACHE_TTL_SECONDS:
            points = cached[1]
            return MetricResult(points, interval, None if points is not None else "glassnode cached miss")

        result = await self._fetch(path, asset, interval)
        self._cache[cache_key] = (time.time(), result.points)
        return result

    async def _fetch(self, path: str, asset: str, interval: str) -> MetricResult:
        session = await self._get_session()
        now = int(time.time())
        params = {
            "a": asset,
            "i": interval,
            "s": now - 7 * 24 * 3600,
            "u": now,
            "f": "json",
            # Accepted for debug per spec; X-Api-Key header is the real auth.
            "api_key": self.api_key,
        }
        headers = {"X-Api-Key": self.api_key}
        url = f"{BASE_URL}{path}"

        try:
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status in (401, 403):
                    self._key_valid = False
                    logger.warning("glassnode unauthorized (%s)", path)
                    return MetricResult(None, interval, "glassnode unauthorized")
                if resp.status == 429:
                    logger.info("glassnode rate limited (%s)", path)
                    return MetricResult(None, interval, "glassnode rate limit")
                if resp.status == 400 and interval == "1h":
                    return await self._fetch(path, asset, "24h")
                if resp.status == 404:
                    return MetricResult(None, interval, "glassnode metric not found")
                if resp.status != 200:
                    return MetricResult(None, interval, f"glassnode http {resp.status}")
                data = await resp.json()
        except Exception as exc:
            logger.info("glassnode request failed (%s): %s", path, exc)
            return MetricResult(None, interval, "glassnode request failed")

        if not isinstance(data, list) or not data:
            return MetricResult(None, interval, "glassnode empty series")
        return MetricResult(data, interval, None)
