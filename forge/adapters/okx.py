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

WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
REST_BASE = "https://www.okx.com"
DEPTH_LEVELS = 50


class OKXAdapter(ExchangeAdapter):
    """OKX v5 public adapter (books/trades over WS, funding + OI via REST)."""

    name = "okx"
    rest_poll_interval = 30.0

    def __init__(self, symbols: list[str]):
        super().__init__(symbols)
        self._books = {s: LocalOrderBook() for s in symbols}
        self._http: aiohttp.ClientSession | None = None

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession()
        return self._http

    async def _ws_once(self) -> None:
        args = []
        for s in self.symbols:
            inst = exchange_symbol(s, "okx")
            args += [
                {"channel": "books", "instId": inst},
                {"channel": "trades", "instId": inst},
            ]
        async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": args}))
            logger.info("[okx] connected, subscribed %s symbols", len(self.symbols))
            async for raw in ws:
                if raw == "pong":
                    continue
                msg = json.loads(raw)
                arg = msg.get("arg", {})
                channel = arg.get("channel")
                if channel == "books":
                    await self._handle_book(arg["instId"], msg)
                elif channel == "trades":
                    await self._handle_trades(arg["instId"], msg)

    async def _handle_book(self, inst_id: str, msg: dict) -> None:
        canonical = canonical_from_exchange("okx", inst_id)
        if canonical is None:
            return
        book = self._books[canonical]
        action = msg.get("action")
        for entry in msg.get("data", []):
            bids = [(float(p), float(q)) for p, q, *_ in entry["bids"]]
            asks = [(float(p), float(q)) for p, q, *_ in entry["asks"]]
            if action == "snapshot":
                book.apply_snapshot(bids, asks)
            else:
                book.apply_delta(bids, asks)
            bids_n, asks_n = book.top_n(DEPTH_LEVELS)
            snapshot = OrderBookSnapshot(
                exchange=self.name,
                symbol=canonical,
                timestamp=int(entry["ts"]) / 1000,
                bids=bids_n,
                asks=asks_n,
            )
            await self._emit_orderbook(snapshot)

    async def _handle_trades(self, inst_id: str, msg: dict) -> None:
        canonical = canonical_from_exchange("okx", inst_id)
        if canonical is None:
            return
        for t in msg.get("data", []):
            trade = Trade(
                exchange=self.name,
                symbol=canonical,
                price=float(t["px"]),
                qty=float(t["sz"]),
                side=Side.BUY if t["side"] == "buy" else Side.SELL,
                timestamp=int(t["ts"]) / 1000,
            )
            await self._emit_trade(trade)

    async def _rest_poll_once(self) -> None:
        http = await self._get_http()
        for canonical in self.symbols:
            inst = exchange_symbol(canonical, "okx")
            try:
                async with http.get(f"{REST_BASE}/api/v5/public/funding-rate", params={"instId": inst}) as resp:
                    data = (await resp.json())["data"][0]
                funding = FundingRate(
                    exchange=self.name,
                    symbol=canonical,
                    rate=float(data["fundingRate"]),
                    next_funding_time=int(data["nextFundingTime"]) / 1000,
                    timestamp=time.time(),
                )
                await self._emit_funding(funding)

                async with http.get(f"{REST_BASE}/api/v5/public/open-interest", params={"instId": inst}) as resp:
                    oi_data = (await resp.json())["data"][0]
                if oi_data.get("oiUsd"):
                    value_usd = float(oi_data["oiUsd"])
                else:
                    # Older responses only carry oiCcy (base-asset units) or
                    # oi (contracts); fall back to converting via mid price.
                    oi_units = float(oi_data.get("oiCcy") or oi_data["oi"])
                    mark_price = self.liquidity_mid_price_hint(canonical)
                    value_usd = oi_units * mark_price if mark_price else oi_units
                oi = OpenInterest(
                    exchange=self.name,
                    symbol=canonical,
                    value_usd=value_usd,
                    timestamp=time.time(),
                )
                await self._emit_oi(oi)
            except Exception:
                logger.exception("[okx] REST poll failed for %s", inst)

    def liquidity_mid_price_hint(self, canonical: str) -> float | None:
        book = self._books.get(canonical)
        if not book:
            return None
        bid, ask = book.best_bid(), book.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2
