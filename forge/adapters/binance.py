from __future__ import annotations

import json
import logging
import time

import aiohttp
import websockets

from forge.adapters.base import ExchangeAdapter
from forge.engine.local_book import LocalOrderBook
from forge.models import FundingRate, OpenInterest, OrderBookSnapshot, Side, Trade
from forge.normalizer import canonical_from_exchange, exchange_symbol

logger = logging.getLogger(__name__)

WS_BASE = "wss://fstream.binance.com"
REST_BASE = "https://fapi.binance.com"
DEPTH_LEVELS = 50


class BinanceAdapter(ExchangeAdapter):
    """Binance USDT-M Futures adapter.

    Order book is maintained locally per Binance's documented procedure:
    buffer the diff-depth stream, bootstrap from a REST snapshot, drop
    buffered events older than the snapshot, then apply the rest while
    checking that each event's `pu` matches the previous applied `u` to
    detect gaps and force a resync.
    """

    name = "binance"
    rest_poll_interval = 30.0

    def __init__(self, symbols: list[str]):
        super().__init__(symbols)
        self._books = {s: LocalOrderBook() for s in symbols}
        self._buffers: dict[str, list[dict]] = {s: [] for s in symbols}
        self._synced: dict[str, bool] = {s: False for s in symbols}
        self._last_u: dict[str, int] = {s: 0 for s in symbols}
        self._http: aiohttp.ClientSession | None = None

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    async def _ws_once(self) -> None:
        for s in self.symbols:
            self._buffers[s] = []
            self._synced[s] = False
        depth_streams = [f"{exchange_symbol(s, 'binance').lower()}@depth@100ms" for s in self.symbols]
        trade_streams = [f"{exchange_symbol(s, 'binance').lower()}@aggTrade" for s in self.symbols]
        url = f"{WS_BASE}/stream?streams=" + "/".join(depth_streams + trade_streams)
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            logger.info("[binance] connected, %s symbols", len(self.symbols))
            async for raw in ws:
                msg = json.loads(raw)
                stream = msg.get("stream", "")
                data = msg.get("data", {})
                if stream.endswith("@aggTrade"):
                    await self._handle_trade(data)
                elif "@depth" in stream:
                    await self._handle_depth(data)

    async def _handle_depth(self, data: dict) -> None:
        canonical = canonical_from_exchange("binance", data["s"])
        if canonical is None:
            return
        if not self._synced[canonical]:
            self._buffers[canonical].append(data)
            await self._try_sync(canonical)
            return
        if data["pu"] != self._last_u[canonical]:
            logger.warning(
                "[binance] %s sequence gap (pu=%s expected=%s), resyncing",
                canonical, data["pu"], self._last_u[canonical],
            )
            self._synced[canonical] = False
            self._buffers[canonical] = [data]
            await self._try_sync(canonical)
            return
        await self._apply_update(canonical, data)

    async def _try_sync(self, canonical: str) -> None:
        symbol = exchange_symbol(canonical, "binance")
        http = await self._get_http()
        async with http.get(f"{REST_BASE}/fapi/v1/depth", params={"symbol": symbol, "limit": 1000}) as resp:
            snap = await resp.json()
        last_update_id = snap["lastUpdateId"]
        book = self._books[canonical]
        book.apply_snapshot(
            [(float(p), float(q)) for p, q in snap["bids"]],
            [(float(p), float(q)) for p, q in snap["asks"]],
        )
        buffered = [e for e in self._buffers[canonical] if e["u"] >= last_update_id + 1]
        if not buffered:
            return
        first = buffered[0]
        if not (first["U"] <= last_update_id + 1 <= first["u"]):
            self._buffers[canonical] = [first]
            return
        for event in buffered:
            await self._apply_update(canonical, event)
        self._synced[canonical] = True
        self._buffers[canonical] = []

    async def _apply_update(self, canonical: str, data: dict) -> None:
        book = self._books[canonical]
        book.apply_delta(
            [(float(p), float(q)) for p, q in data["b"]],
            [(float(p), float(q)) for p, q in data["a"]],
        )
        self._last_u[canonical] = data["u"]
        bids, asks = book.top_n(DEPTH_LEVELS)
        snapshot = OrderBookSnapshot(
            exchange=self.name,
            symbol=canonical,
            timestamp=data["E"] / 1000,
            bids=bids,
            asks=asks,
            sequence=data["u"],
        )
        await self._emit_orderbook(snapshot)

    async def _handle_trade(self, data: dict) -> None:
        canonical = canonical_from_exchange("binance", data["s"])
        if canonical is None:
            return
        trade = Trade(
            exchange=self.name,
            symbol=canonical,
            price=float(data["p"]),
            qty=float(data["q"]),
            side=Side.SELL if data["m"] else Side.BUY,
            timestamp=data["T"] / 1000,
        )
        await self._emit_trade(trade)

    async def _rest_poll_once(self) -> None:
        http = await self._get_http()
        for canonical in self.symbols:
            symbol = exchange_symbol(canonical, "binance")
            try:
                async with http.get(f"{REST_BASE}/fapi/v1/premiumIndex", params={"symbol": symbol}) as resp:
                    data = await resp.json()
                funding = FundingRate(
                    exchange=self.name,
                    symbol=canonical,
                    rate=float(data["lastFundingRate"]),
                    next_funding_time=data["nextFundingTime"] / 1000,
                    timestamp=time.time(),
                )
                await self._emit_funding(funding)

                async with http.get(f"{REST_BASE}/fapi/v1/openInterest", params={"symbol": symbol}) as resp:
                    oi_data = await resp.json()
                oi = OpenInterest(
                    exchange=self.name,
                    symbol=canonical,
                    value_usd=float(oi_data["openInterest"]) * float(data["markPrice"]),
                    timestamp=time.time(),
                )
                await self._emit_oi(oi)
            except Exception:
                logger.exception("[binance] REST poll failed for %s", symbol)
