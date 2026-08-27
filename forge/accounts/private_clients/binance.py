from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse

from config.settings import SYMBOLS
from forge.accounts.models import Balance, InvalidCredentialsError, OpenOrder, Position, RawFill
from forge.accounts.private_clients.base import PrivateExchangeClient
from forge.normalizer import exchange_symbol

REST_BASE = "https://fapi.binance.com"

# Auth-related error codes per Binance Futures API docs. Other codes
# (rate limits, bad params, ...) are not credential problems and should
# not be reported as INVALID connections - see README caveat about
# validating exchange error codes against current official docs.
_AUTH_ERROR_CODES = {-1022, -2008, -2014, -2015}


class BinancePrivateClient(PrivateExchangeClient):
    exchange = "binance"

    def _sign(self, query: str) -> str:
        return hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def _signed_get(self, path: str, params: dict | None = None):
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", 5000)
        query = urllib.parse.urlencode(params)
        query = f"{query}&signature={self._sign(query)}"
        headers = {"X-MBX-APIKEY": self._api_key}
        async with self._http.get(f"{REST_BASE}{path}?{query}", headers=headers) as resp:
            data = await resp.json()
            if resp.status in (401, 403) or (isinstance(data, dict) and data.get("code") in _AUTH_ERROR_CODES):
                raise InvalidCredentialsError(f"binance: {data}")
            if isinstance(data, dict) and "code" in data:
                # Any other Binance error shape (rate limit, bad params, ...) -
                # not a credential problem, so don't mask it as one, but don't
                # let callers try to iterate/index it as a normal payload either.
                raise RuntimeError(f"binance API error: {data}")
            if not isinstance(data, list):
                # e.g. an empty body (aiohttp's .json() returns None) on a
                # non-401/403 error status we don't otherwise recognize.
                raise RuntimeError(f"binance: unexpected response (status {resp.status}): {data!r}")
            return data

    async def get_balance(self) -> Balance:
        data = await self._signed_get("/fapi/v2/balance")
        total = sum(float(a["balance"]) for a in data)
        available = sum(float(a["availableBalance"]) for a in data)
        return Balance(exchange=self.exchange, total_equity_usd=total, available_usd=available, raw={"assets": data})

    async def get_positions(self) -> list[Position]:
        data = await self._signed_get("/fapi/v2/positionRisk")
        positions = []
        for p in data:
            amt = float(p["positionAmt"])
            if amt == 0:
                continue
            positions.append(
                Position(
                    exchange=self.exchange,
                    symbol=p["symbol"],
                    side="LONG" if amt > 0 else "SHORT",
                    size=abs(amt),
                    entry_price=float(p["entryPrice"]),
                    unrealized_pnl=float(p["unRealizedProfit"]),
                    leverage=float(p["leverage"]) if p.get("leverage") else None,
                )
            )
        return positions

    async def get_open_orders(self) -> list[OpenOrder]:
        data = await self._signed_get("/fapi/v1/openOrders")
        return [
            OpenOrder(
                exchange=self.exchange,
                order_id=str(o["orderId"]),
                symbol=o["symbol"],
                side=o["side"],
                price=float(o["price"]),
                qty=float(o["origQty"]),
                status=o["status"],
            )
            for o in data
        ]

    async def get_recent_trades(self) -> list[RawFill]:
        fills: list[RawFill] = []
        for canonical in SYMBOLS:
            symbol = exchange_symbol(canonical, "binance")
            data = await self._signed_get("/fapi/v1/userTrades", {"symbol": symbol, "limit": 100})
            for t in data:
                fills.append(
                    RawFill(
                        exchange=self.exchange,
                        external_id=str(t["id"]),
                        symbol=canonical,
                        side=t["side"],
                        qty=float(t["qty"]),
                        price=float(t["price"]),
                        fee=float(t["commission"]),
                        realized_pnl=float(t["realizedPnl"]) if t.get("realizedPnl") not in (None, "") else None,
                        order_id=str(t["orderId"]),
                        timestamp=t["time"] / 1000,
                    )
                )
        return fills
