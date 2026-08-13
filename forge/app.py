from __future__ import annotations

import asyncio
import logging
import sys

from aiohttp import web

from config.settings import HTTP_HOST, HTTP_PORT, MIN_EXCHANGES_FOR_FULL_CONFIDENCE, SYMBOLS
from forge.adapters.base import ExchangeAdapter
from forge.adapters.binance import BinanceAdapter
from forge.adapters.bitget import BitgetAdapter
from forge.adapters.bybit import BybitAdapter
from forge.adapters.okx import OKXAdapter
from forge.engine.score_engine import SymbolMarketState
from forge.interface import Heatmap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("forge.app")


def build_adapters(symbols: list[str]) -> list[ExchangeAdapter]:
    return [
        BinanceAdapter(symbols),
        OKXAdapter(symbols),
        BybitAdapter(symbols),
        BitgetAdapter(symbols),
    ]


def _wire_adapter(adapter: ExchangeAdapter, states: dict[str, SymbolMarketState]) -> None:
    async def on_orderbook(event):
        state = states.get(event.symbol)
        if state:
            state.on_orderbook(event)

    async def on_trade(event):
        state = states.get(event.symbol)
        if state:
            state.on_trade(event)

    async def on_open_interest(event):
        state = states.get(event.symbol)
        if state:
            state.on_open_interest(event)

    async def on_funding(event):
        state = states.get(event.symbol)
        if state:
            state.on_funding(event)

    async def on_liquidation(event):
        state = states.get(event.symbol)
        if state:
            state.on_liquidation(event)

    adapter.on_orderbook = on_orderbook
    adapter.on_trade = on_trade
    adapter.on_open_interest = on_open_interest
    adapter.on_funding = on_funding
    adapter.on_liquidation = on_liquidation


async def _start_http_server(heatmap: Heatmap) -> web.AppRunner:
    async def get_signal(request: web.Request) -> web.Response:
        symbol = request.match_info["symbol"].upper()
        try:
            return web.json_response(heatmap.get_signal(symbol))
        except KeyError:
            return web.json_response({"error": f"unknown symbol {symbol}"}, status=404)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    web_app = web.Application()
    web_app.router.add_get("/signal/{symbol}", get_signal)
    web_app.router.add_get("/health", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    logger.info("HTTP API listening on http://%s:%s", HTTP_HOST, HTTP_PORT)
    return runner


async def main() -> None:
    states = {s: SymbolMarketState(s, MIN_EXCHANGES_FOR_FULL_CONFIDENCE) for s in SYMBOLS}
    heatmap = Heatmap(states)
    adapters = build_adapters(SYMBOLS)
    for adapter in adapters:
        _wire_adapter(adapter, states)

    runner = await _start_http_server(heatmap)
    try:
        await asyncio.gather(*(a.run_forever() for a in adapters))
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
