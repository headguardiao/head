from __future__ import annotations

import asyncio
import logging
import pathlib
import sys

from aiohttp import web

from config.settings import API_KEY, DB_PATH, HTTP_HOST, HTTP_PORT, MIN_EXCHANGES_FOR_FULL_CONFIDENCE, SYMBOLS
from forge.accounts.api import register_routes as register_accounts_routes
from forge.accounts.db import ConnectionsRepo
from forge.accounts.db import init_db as init_accounts_db
from forge.accounts.service import AccountsService
from forge.adapters.base import ExchangeAdapter
from forge.adapters.binance import BinanceAdapter
from forge.adapters.bitget import BitgetAdapter
from forge.adapters.bybit import BybitAdapter
from forge.adapters.okx import OKXAdapter
from forge.auth import build_auth_middleware
from forge.engine.score_engine import SymbolMarketState
from forge.insights.api import register_routes as register_insights_routes
from forge.insights.db import InsightsRepo
from forge.insights.db import init_db as init_insights_db
from forge.insights.service import InsightsService
from forge.interface import Heatmap
from forge.ledger.api import register_routes as register_ledger_routes
from forge.ledger.db import StrategyTradesRepo, TradesRepo
from forge.ledger.db import init_db as init_ledger_db
from forge.ledger.service import LedgerService
from forge.strategies.api import register_routes as register_strategies_routes
from forge.strategies.db import StrategiesRepo
from forge.strategies.db import init_db as init_strategies_db
from forge.strategies.service import StrategyService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("forge.app")

STATIC_DIR = pathlib.Path(__file__).parent / "static"


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


async def _start_http_server(
    heatmap: Heatmap,
    accounts_service: AccountsService,
    strategy_service: StrategyService,
    ledger_service: LedgerService,
    insights_service: InsightsService,
) -> web.AppRunner:
    async def get_signal(request: web.Request) -> web.Response:
        symbol = request.match_info["symbol"].upper()
        try:
            return web.json_response(await heatmap.get_signal(symbol))
        except KeyError:
            return web.json_response({"error": f"unknown symbol {symbol}"}, status=404)

    async def get_sentiment(request: web.Request) -> web.Response:
        # Unlike /signal, any symbol is accepted - Camada C sentiment
        # is independent Binance-derivatives data, not gated by which
        # symbols this instance tracks order books for.
        symbol = request.match_info["symbol"].upper()
        return web.json_response(await heatmap.get_sentiment(symbol))

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def dashboard(_request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "dashboard.html")

    web_app = web.Application(middlewares=[build_auth_middleware(API_KEY)])
    web_app.router.add_get("/signal/{symbol}", get_signal)
    web_app.router.add_get("/sentiment/{symbol}", get_sentiment)
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/dashboard", dashboard)
    web_app.router.add_get("/", dashboard)
    register_accounts_routes(web_app, accounts_service)
    register_strategies_routes(web_app, strategy_service)
    register_ledger_routes(web_app, ledger_service)
    register_insights_routes(web_app, insights_service)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()
    logger.info("HTTP API listening on http://%s:%s", HTTP_HOST, HTTP_PORT)
    return runner


async def main() -> None:
    await init_accounts_db(DB_PATH)
    await init_strategies_db(DB_PATH)
    await init_ledger_db(DB_PATH)
    await init_insights_db(DB_PATH)

    trades_repo = TradesRepo(DB_PATH)
    strategy_trades_repo = StrategyTradesRepo(DB_PATH)

    accounts_service = AccountsService(ConnectionsRepo(DB_PATH))
    strategy_service = StrategyService(StrategiesRepo(DB_PATH))
    ledger_service = LedgerService(accounts_service, trades_repo, strategy_trades_repo, StrategiesRepo(DB_PATH))
    insights_service = InsightsService(InsightsRepo(DB_PATH), trades_repo, strategy_trades_repo)

    states = {s: SymbolMarketState(s, MIN_EXCHANGES_FOR_FULL_CONFIDENCE) for s in SYMBOLS}
    heatmap = Heatmap(states)
    adapters = build_adapters(SYMBOLS)
    for adapter in adapters:
        _wire_adapter(adapter, states)

    runner = await _start_http_server(heatmap, accounts_service, strategy_service, ledger_service, insights_service)
    try:
        await asyncio.gather(*(a.run_forever() for a in adapters))
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
