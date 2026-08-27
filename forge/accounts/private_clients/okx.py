from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

from forge.accounts.models import Balance, InvalidCredentialsError, OpenOrder, Position, RawFill
from forge.accounts.private_clients.base import PrivateExchangeClient
from forge.normalizer import canonical_from_exchange

REST_BASE = "https://www.okx.com"
INST_TYPE = "SWAP"

# Auth-related code values per OKX v5 API docs. Other non-"0" codes
# (rate limits, bad params, ...) are not credential problems - see
# README caveat about validating exchange error codes against current
# official docs.
_AUTH_CODES = {"50110", "50111", "50112", "50113", "50114"}


class OKXPrivateClient(PrivateExchangeClient):
    exchange = "okx"

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        prehash = f"{timestamp}{method}{request_path}{body}"
        digest = hmac.new(self._api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    async def _signed_get(self, path: str) -> list:
        timestamp = self._timestamp()
        headers = {
            "OK-ACCESS-KEY": self._api_key,
            "OK-ACCESS-SIGN": self._sign(timestamp, "GET", path),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase or "",
            "Content-Type": "application/json",
        }
        async with self._http.get(f"{REST_BASE}{path}", headers=headers) as resp:
            # aiohttp's .json() returns None for an empty body - check
            # status/body shape before ever calling .get() on the payload.
            data = await resp.json()
            if resp.status in (401, 403):
                raise InvalidCredentialsError(f"okx: HTTP {resp.status} {data!r}")
            if not isinstance(data, dict):
                raise RuntimeError(f"okx: unexpected response body: {data!r}")
            code = data.get("code")
            if code in _AUTH_CODES:
                raise InvalidCredentialsError(f"okx: {data}")
            if code != "0":
                raise RuntimeError(f"okx API error: {data}")
            return data.get("data") or []

    async def get_balance(self) -> Balance:
        data = await self._signed_get("/api/v5/account/balance")
        if not data:
            return Balance(exchange=self.exchange, total_equity_usd=0.0, available_usd=0.0, raw={})
        acc = data[0]
        return Balance(
            exchange=self.exchange,
            total_equity_usd=float(acc.get("totalEq") or 0.0),
            available_usd=float(acc.get("availEq") or acc.get("totalEq") or 0.0),
            raw=acc,
        )

    async def get_positions(self) -> list[Position]:
        data = await self._signed_get(f"/api/v5/account/positions?instType={INST_TYPE}")
        positions = []
        for p in data:
            size = float(p.get("pos") or 0)
            if size == 0:
                continue
            positions.append(
                Position(
                    exchange=self.exchange,
                    symbol=p["instId"],
                    side=p.get("posSide", "").upper() or ("LONG" if size > 0 else "SHORT"),
                    size=abs(size),
                    entry_price=float(p.get("avgPx") or 0.0),
                    unrealized_pnl=float(p.get("upl") or 0.0),
                    leverage=float(p["lever"]) if p.get("lever") else None,
                )
            )
        return positions

    async def get_open_orders(self) -> list[OpenOrder]:
        data = await self._signed_get(f"/api/v5/trade/orders-pending?instType={INST_TYPE}")
        return [
            OpenOrder(
                exchange=self.exchange,
                order_id=o["ordId"],
                symbol=o["instId"],
                side=o.get("side", "").upper(),
                price=float(o.get("px") or 0.0),
                qty=float(o.get("sz") or 0.0),
                status=o.get("state", ""),
            )
            for o in data
        ]

    async def get_recent_trades(self) -> list[RawFill]:
        # /fills (not /fills-history): the latter needs a special access
        # grant on the API key. This one only covers the last 3 days -
        # fine for "recent trades", not for a historical backfill.
        data = await self._signed_get(f"/api/v5/trade/fills?instType={INST_TYPE}&limit=100")
        fills = []
        for f in data:
            canonical = canonical_from_exchange("okx", f["instId"])
            if canonical is None:
                continue
            fills.append(
                RawFill(
                    exchange=self.exchange,
                    external_id=f["tradeId"],
                    symbol=canonical,
                    side=f.get("side", "").upper(),
                    qty=float(f.get("fillSz") or 0.0),
                    price=float(f.get("fillPx") or 0.0),
                    fee=abs(float(f.get("fee") or 0.0)),
                    realized_pnl=None,  # OKX doesn't report per-fill realized PnL on this endpoint
                    order_id=f.get("ordId", ""),
                    timestamp=int(f.get("ts") or 0) / 1000,
                )
            )
        return fills
