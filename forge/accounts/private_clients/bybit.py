from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse

from forge.accounts.models import Balance, InvalidCredentialsError, OpenOrder, Position, RawFill
from forge.accounts.private_clients.base import PrivateExchangeClient
from forge.normalizer import canonical_from_exchange

REST_BASE = "https://api.bybit.com"
RECV_WINDOW = "5000"

# Auth-related retCode values per Bybit v5 API docs. Other non-zero
# codes (rate limits, bad params, ...) are not credential problems -
# see README caveat about validating exchange error codes against
# current official docs.
_AUTH_RET_CODES = {10003, 10004, 10005, 33004}


class BybitPrivateClient(PrivateExchangeClient):
    exchange = "bybit"

    def _sign(self, timestamp: str, query: str) -> str:
        payload = timestamp + self._api_key + RECV_WINDOW + query
        return hmac.new(self._api_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    async def _signed_get(self, path: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        query = urllib.parse.urlencode(params)
        timestamp = str(int(time.time() * 1000))
        headers = {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": self._sign(timestamp, query),
        }
        url = f"{REST_BASE}{path}"
        if query:
            url += f"?{query}"
        async with self._http.get(url, headers=headers) as resp:
            # aiohttp's .json() returns None for an empty body, which Bybit
            # sends on some 401s - check status/body shape before ever
            # calling .get() on the parsed payload.
            data = await resp.json()
            if resp.status in (401, 403):
                raise InvalidCredentialsError(f"bybit: HTTP {resp.status} {data!r}")
            if not isinstance(data, dict):
                raise RuntimeError(f"bybit: unexpected response body: {data!r}")
            ret_code = data.get("retCode")
            if ret_code in _AUTH_RET_CODES:
                raise InvalidCredentialsError(f"bybit: {data}")
            if ret_code != 0:
                raise RuntimeError(f"bybit API error: {data}")
            return data.get("result", {})

    async def get_balance(self) -> Balance:
        result = await self._signed_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        accounts = result.get("list", [])
        if not accounts:
            return Balance(exchange=self.exchange, total_equity_usd=0.0, available_usd=0.0, raw=result)
        acc = accounts[0]
        return Balance(
            exchange=self.exchange,
            total_equity_usd=float(acc.get("totalEquity") or 0.0),
            available_usd=float(acc.get("totalAvailableBalance") or 0.0),
            raw=result,
        )

    async def get_positions(self) -> list[Position]:
        result = await self._signed_get("/v5/position/list", {"category": "linear", "settleCoin": "USDT"})
        positions = []
        for p in result.get("list", []):
            size = float(p.get("size") or 0)
            if size == 0:
                continue
            positions.append(
                Position(
                    exchange=self.exchange,
                    symbol=p["symbol"],
                    side=p.get("side", "").upper() or "UNKNOWN",
                    size=size,
                    entry_price=float(p.get("avgPrice") or 0.0),
                    unrealized_pnl=float(p.get("unrealisedPnl") or 0.0),
                    leverage=float(p["leverage"]) if p.get("leverage") else None,
                )
            )
        return positions

    async def get_open_orders(self) -> list[OpenOrder]:
        result = await self._signed_get("/v5/order/realtime", {"category": "linear", "settleCoin": "USDT"})
        return [
            OpenOrder(
                exchange=self.exchange,
                order_id=o["orderId"],
                symbol=o["symbol"],
                side=o.get("side", "").upper(),
                price=float(o.get("price") or 0.0),
                qty=float(o.get("qty") or 0.0),
                status=o.get("orderStatus", ""),
            )
            for o in result.get("list", [])
        ]

    async def get_recent_trades(self) -> list[RawFill]:
        result = await self._signed_get("/v5/execution/list", {"category": "linear", "limit": 100})
        fills = []
        for e in result.get("list", []):
            canonical = canonical_from_exchange("bybit", e["symbol"])
            if canonical is None:
                continue
            fills.append(
                RawFill(
                    exchange=self.exchange,
                    external_id=e["execId"],
                    symbol=canonical,
                    side=e.get("side", "").upper(),
                    qty=float(e.get("execQty") or 0.0),
                    price=float(e.get("execPrice") or 0.0),
                    fee=float(e.get("execFee") or 0.0),
                    realized_pnl=float(e["closedPnl"]) if e.get("closedPnl") not in (None, "") else None,
                    order_id=e.get("orderId", ""),
                    timestamp=int(e.get("execTime") or 0) / 1000,
                )
            )
        return fills
