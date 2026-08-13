from __future__ import annotations

import json
import logging
import time

import aiohttp
import websockets

from forge.adapters.base import ExchangeAdapter
from forge.engine.local_book import LocalOrderBook
from forge.models import FundingRate, Liquidation, OpenInterest, OrderBookSnapshot, Side, Trade
from forge.normalizer import canonical_from_exchange, exchange_symbol

logger = logging.getLogger(__name__)

WS_URL = "wss://stream.bybit.com/v5/public/linear"
REST_BASE = "https://api.bybit.com"
DEPTH_LEVELS = 50


class BybitAdapter(ExchangeAdapter):
    """Bybit v5 linear (USDT perpetual) adapter. Bybit streams liquidations
    directly, so this is also the only core adapter that feeds
    on_liquidation without a REST fallback."""

    name = "bybit"
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
        topics = []
        for s in self.symbols:
            sym = exchange_symbol(s, "bybit")
            # NOTE: Bybit deprecated the per-liquidation "liquidation.<symbol>"
            # topic in favor of "allLiquidation.<symbol>". Subscribing to the
            # old name doesn't error - the server silently stops pushing
            # *any* data (not just liquidations) for the whole connection,
            # which is why this was found via live testing rather than an
            # exception in the logs.
            topics += [f"orderbook.50.{sym}", f"publicTrade.{sym}", f"allLiquidation.{sym}"]
        async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": topics}))
            logger.info("[bybit] connected, subscribed %s topics", len(topics))
            async for raw in ws:
                msg = json.loads(raw)
                topic = msg.get("topic", "")
                if topic.startswith("orderbook."):
                    await self._handle_book(msg)
                elif topic.startswith("publicTrade."):
                    await self._handle_trades(msg)
                elif topic.startswith("allLiquidation."):
                    await self._handle_liquidation(msg)

    async def _handle_book(self, msg: dict) -> None:
        data = msg["data"]
        canonical = canonical_from_exchange("bybit", data["s"])
        if canonical is None:
            return
        book = self._books[canonical]
        bids = [(float(p), float(q)) for p, q in data.get("b", [])]
        asks = [(float(p), float(q)) for p, q in data.get("a", [])]
        if msg.get("type") == "snapshot":
            book.apply_snapshot(bids, asks)
        else:
            book.apply_delta(bids, asks)
        bids_n, asks_n = book.top_n(DEPTH_LEVELS)
        snapshot = OrderBookSnapshot(
            exchange=self.name,
            symbol=canonical,
            timestamp=msg["ts"] / 1000,
            bids=bids_n,
            asks=asks_n,
            sequence=data.get("u", 0),
        )
        await self._emit_orderbook(snapshot)

    async def _handle_trades(self, msg: dict) -> None:
        for t in msg.get("data", []):
            canonical = canonical_from_exchange("bybit", t["s"])
            if canonical is None:
                continue
            trade = Trade(
                exchange=self.name,
                symbol=canonical,
                price=float(t["p"]),
                qty=float(t["v"]),
                side=Side.BUY if t["S"] == "Buy" else Side.SELL,
                timestamp=int(t["T"]) / 1000,
            )
            await self._emit_trade(trade)

    async def _handle_liquidation(self, msg: dict) -> None:
        # allLiquidation.<symbol> pushes a list of entries: s, S, v, p, T.
        for entry in msg.get("data", []):
            canonical = canonical_from_exchange("bybit", entry["s"])
            if canonical is None:
                continue
            liq = Liquidation(
                exchange=self.name,
                symbol=canonical,
                side=Side.BUY if entry["S"] == "Buy" else Side.SELL,
                price=float(entry["p"]),
                qty=float(entry["v"]),
                timestamp=int(entry["T"]) / 1000,
            )
            await self._emit_liquidation(liq)

    async def _rest_poll_once(self) -> None:
        http = await self._get_http()
        for canonical in self.symbols:
            sym = exchange_symbol(canonical, "bybit")
            try:
                async with http.get(
                    f"{REST_BASE}/v5/market/tickers", params={"category": "linear", "symbol": sym}
                ) as resp:
                    data = (await resp.json())["result"]["list"][0]
                funding = FundingRate(
                    exchange=self.name,
                    symbol=canonical,
                    rate=float(data["fundingRate"]),
                    next_funding_time=int(data.get("nextFundingTime") or 0) / 1000,
                    timestamp=time.time(),
                )
                await self._emit_funding(funding)

                oi = OpenInterest(
                    exchange=self.name,
                    symbol=canonical,
                    value_usd=float(data["openInterestValue"]),
                    timestamp=time.time(),
                )
                await self._emit_oi(oi)
            except Exception:
                logger.exception("[bybit] REST poll failed for %s", sym)
