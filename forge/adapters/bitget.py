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

WS_URL = "wss://ws.bitget.com/v2/ws/public"
REST_BASE = "https://api.bitget.com"
DEPTH_LEVELS = 50
PRODUCT_TYPE = "USDT-FUTURES"


class BitgetAdapter(ExchangeAdapter):
    """Bitget v2 USDT-M futures adapter."""

    name = "bitget"
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
            inst = exchange_symbol(s, "bitget")
            args += [
                {"instType": PRODUCT_TYPE, "channel": "books15", "instId": inst},
                {"instType": PRODUCT_TYPE, "channel": "trade", "instId": inst},
            ]
        async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": args}))
            logger.info("[bitget] connected, subscribed %s symbols", len(self.symbols))
            async for raw in ws:
                if raw == "pong":
                    continue
                msg = json.loads(raw)
                arg = msg.get("arg", {})
                channel = arg.get("channel")
                if channel == "books15":
                    await self._handle_book(arg["instId"], msg)
                elif channel == "trade":
                    await self._handle_trades(arg["instId"], msg)

    async def _handle_book(self, inst_id: str, msg: dict) -> None:
        canonical = canonical_from_exchange("bitget", inst_id)
        if canonical is None:
            return
        book = self._books[canonical]
        action = msg.get("action")
        for entry in msg.get("data", []):
            bids = [(float(p), float(q)) for p, q in entry["bids"]]
            asks = [(float(p), float(q)) for p, q in entry["asks"]]
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
        canonical = canonical_from_exchange("bitget", inst_id)
        if canonical is None:
            return
        for t in msg.get("data", []):
            trade = Trade(
                exchange=self.name,
                symbol=canonical,
                price=float(t["price"]),
                qty=float(t["size"]),
                side=Side.BUY if t["side"] == "buy" else Side.SELL,
                timestamp=int(t["ts"]) / 1000,
            )
            await self._emit_trade(trade)

    async def _rest_poll_once(self) -> None:
        http = await self._get_http()
        for canonical in self.symbols:
            inst = exchange_symbol(canonical, "bitget")
            try:
                async with http.get(
                    f"{REST_BASE}/api/v2/mix/market/current-fund-rate",
                    params={"symbol": inst, "productType": PRODUCT_TYPE},
                ) as resp:
                    data = (await resp.json())["data"][0]
                # Bitget's current-fund-rate endpoint does not expose the
                # next settlement timestamp; left at 0 until validated
                # against a dedicated endpoint (see README caveats).
                funding = FundingRate(
                    exchange=self.name,
                    symbol=canonical,
                    rate=float(data["fundingRate"]),
                    next_funding_time=0.0,
                    timestamp=time.time(),
                )
                await self._emit_funding(funding)

                async with http.get(
                    f"{REST_BASE}/api/v2/mix/market/open-interest",
                    params={"symbol": inst, "productType": PRODUCT_TYPE},
                ) as resp:
                    oi_payload = await resp.json()
                oi_list = oi_payload["data"]["openInterestList"]
                oi_size = float(oi_list[0]["size"])
                mark_price = self.liquidity_mid_price_hint(canonical)
                oi = OpenInterest(
                    exchange=self.name,
                    symbol=canonical,
                    value_usd=oi_size * mark_price if mark_price else oi_size,
                    timestamp=time.time(),
                )
                await self._emit_oi(oi)
            except Exception:
                logger.exception("[bitget] REST poll failed for %s", inst)

    def liquidity_mid_price_hint(self, canonical: str) -> float | None:
        book = self._books.get(canonical)
        if not book:
            return None
        bid, ask = book.best_bid(), book.best_ask()
        if bid is None or ask is None:
            return None
        return (bid + ask) / 2
