from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

from forge.accounts.models import Balance, InvalidCredentialsError, OpenOrder, Position, RawFill
from forge.accounts.private_clients.base import PrivateExchangeClient
from forge.normalizer import canonical_from_exchange

REST_BASE = "https://api.bitget.com"
PRODUCT_TYPE = "USDT-FUTURES"

# Auth-related code values per Bitget v2 API docs. Other non-"00000"
# codes (rate limits, bad params, ...) are not credential problems -
# see README caveat about validating exchange error codes against
# current official docs.
_AUTH_CODES = {"40006", "40009", "40012", "40037"}


class BitgetPrivateClient(PrivateExchangeClient):
    exchange = "bitget"

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        prehash = f"{timestamp}{method}{request_path}{body}"
        digest = hmac.new(self._api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    async def _signed_get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        query = urllib.parse.urlencode(params)
        request_path = f"{path}?{query}" if query else path
        timestamp = str(int(time.time() * 1000))
        headers = {
            "ACCESS-KEY": self._api_key,
            "ACCESS-SIGN": self._sign(timestamp, "GET", request_path),
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self._passphrase or "",
            "Content-Type": "application/json",
        }
        async with self._http.get(f"{REST_BASE}{request_path}", headers=headers) as resp:
            # aiohttp's .json() returns None for an empty body - check
            # status/body shape before ever calling .get() on the payload.
            data = await resp.json()
            if resp.status in (401, 403):
                raise InvalidCredentialsError(f"bitget: HTTP {resp.status} {data!r}")
            if not isinstance(data, dict):
                raise RuntimeError(f"bitget: unexpected response body: {data!r}")
            code = data.get("code")
            if code in _AUTH_CODES:
                raise InvalidCredentialsError(f"bitget: {data}")
            if code != "00000":
                raise RuntimeError(f"bitget API error: {data}")
            return data.get("data")

    async def get_balance(self) -> Balance:
        data = await self._signed_get("/api/v2/mix/account/accounts", {"productType": PRODUCT_TYPE})
        accounts = data or []
        total = sum(float(a.get("usdtEquity") or 0.0) for a in accounts)
        available = sum(float(a.get("available") or 0.0) for a in accounts)
        return Balance(exchange=self.exchange, total_equity_usd=total, available_usd=available, raw={"accounts": accounts})

    async def get_positions(self) -> list[Position]:
        data = await self._signed_get(
            "/api/v2/mix/position/all-position", {"productType": PRODUCT_TYPE, "marginCoin": "USDT"}
        )
        positions = []
        for p in data or []:
            size = float(p.get("total") or 0)
            if size == 0:
                continue
            positions.append(
                Position(
                    exchange=self.exchange,
                    symbol=p["symbol"],
                    side=p.get("holdSide", "").upper() or "UNKNOWN",
                    size=size,
                    entry_price=float(p.get("openPriceAvg") or 0.0),
                    unrealized_pnl=float(p.get("unrealizedPL") or 0.0),
                    leverage=float(p["leverage"]) if p.get("leverage") else None,
                )
            )
        return positions

    async def get_open_orders(self) -> list[OpenOrder]:
        data = await self._signed_get("/api/v2/mix/order/orders-pending", {"productType": PRODUCT_TYPE})
        entries = (data or {}).get("entrustedList") or []
        return [
            OpenOrder(
                exchange=self.exchange,
                order_id=str(o["orderId"]),
                symbol=o["symbol"],
                side=o.get("side", "").upper(),
                price=float(o.get("price") or 0.0),
                qty=float(o.get("size") or 0.0),
                status=o.get("state", ""),
            )
            for o in entries
        ]

    async def get_recent_trades(self) -> list[RawFill]:
        data = await self._signed_get("/api/v2/mix/order/fill-history", {"productType": PRODUCT_TYPE, "limit": 100})
        fills_data = (data or {}).get("fillList") or []
        fills = []
        for f in fills_data:
            canonical = canonical_from_exchange("bitget", f["symbol"])
            if canonical is None:
                continue
            fills.append(
                RawFill(
                    exchange=self.exchange,
                    external_id=str(f.get("tradeId")),
                    symbol=canonical,
                    side=f.get("side", "").upper(),
                    qty=float(f.get("baseVolume") or 0.0),
                    price=float(f.get("price") or 0.0),
                    fee=abs(float(f.get("fee") or 0.0)),
                    realized_pnl=float(f["profit"]) if f.get("profit") not in (None, "") else None,
                    order_id=str(f.get("orderId", "")),
                    timestamp=int(f.get("cTime") or 0) / 1000,
                )
            )
        return fills
