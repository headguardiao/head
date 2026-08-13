from __future__ import annotations

import abc
import asyncio
import logging
from typing import Awaitable, Callable, Optional

from forge.models import FundingRate, Liquidation, OpenInterest, OrderBookSnapshot, Trade

logger = logging.getLogger(__name__)

OrderBookCallback = Callable[[OrderBookSnapshot], Awaitable[None]]
TradeCallback = Callable[[Trade], Awaitable[None]]
OICallback = Callable[[OpenInterest], Awaitable[None]]
FundingCallback = Callable[[FundingRate], Awaitable[None]]
LiquidationCallback = Callable[[Liquidation], Awaitable[None]]


class ExchangeAdapter(abc.ABC):
    """Base class every exchange adapter implements.

    Each adapter owns its own WebSocket connection and REST polling loop
    so a protocol change or outage on one exchange cannot affect the
    others (PDF section 3: "cada exchange deve possuir um adapter
    isolado"). WS and REST run as independent reconnect/retry loops via
    run_forever(); subclasses only implement the per-iteration logic.
    """

    name: str = "base"
    rest_poll_interval: float = 30.0

    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.on_orderbook: Optional[OrderBookCallback] = None
        self.on_trade: Optional[TradeCallback] = None
        self.on_open_interest: Optional[OICallback] = None
        self.on_funding: Optional[FundingCallback] = None
        self.on_liquidation: Optional[LiquidationCallback] = None
        self._stop = asyncio.Event()

    async def run_forever(self) -> None:
        await asyncio.gather(self._run_ws_forever(), self._run_rest_forever())

    def stop(self) -> None:
        self._stop.set()

    async def _run_ws_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._ws_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[%s] ws loop crashed, reconnecting in %.0fs", self.name, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _run_rest_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self._rest_poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("[%s] REST poll failed", self.name)
            await asyncio.sleep(self.rest_poll_interval)

    @abc.abstractmethod
    async def _ws_once(self) -> None:
        """Open one WebSocket connection, subscribe and consume messages
        until the connection drops or an error is raised."""

    async def _rest_poll_once(self) -> None:
        """Poll REST endpoints (funding, open interest, ...). No-op
        unless overridden."""
        return

    async def _emit_orderbook(self, snap: OrderBookSnapshot) -> None:
        if self.on_orderbook:
            await self.on_orderbook(snap)

    async def _emit_trade(self, trade: Trade) -> None:
        if self.on_trade:
            await self.on_trade(trade)

    async def _emit_oi(self, oi: OpenInterest) -> None:
        if self.on_open_interest:
            await self.on_open_interest(oi)

    async def _emit_funding(self, funding: FundingRate) -> None:
        if self.on_funding:
            await self.on_funding(funding)

    async def _emit_liquidation(self, liq: Liquidation) -> None:
        if self.on_liquidation:
            await self.on_liquidation(liq)
