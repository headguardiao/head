from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConnectionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INVALID = "INVALID"
    DISABLED = "DISABLED"


class Permission(str, Enum):
    # Only READ_ONLY exists today: no code path in forge/accounts ever
    # calls a trading or withdrawal endpoint (blueprint section 7 -
    # WITHDRAWAL is forbidden by default; TRADING is a future step).
    READ_ONLY = "READ_ONLY"


SUPPORTED_EXCHANGES = ("binance", "bybit", "bitget", "okx")


@dataclass
class ExchangeConnection:
    """Public-facing view of a connection. Never carries key material -
    see forge/accounts/db.py for where encrypted secrets actually live."""

    connection_id: str
    user_id: str
    exchange: str
    account_identifier: str
    permissions: Permission
    status: ConnectionStatus
    last_sync: float | None
    created_at: float
    updated_at: float


@dataclass
class Balance:
    exchange: str
    total_equity_usd: float
    available_usd: float
    raw: dict = field(default_factory=dict)


@dataclass
class Position:
    exchange: str
    symbol: str
    side: str
    size: float
    entry_price: float
    unrealized_pnl: float
    leverage: float | None = None


@dataclass
class OpenOrder:
    exchange: str
    order_id: str
    symbol: str
    side: str
    price: float
    qty: float
    status: str


@dataclass
class RawFill:
    """One fill/execution as reported by an exchange's trade-history
    endpoint - forge/ledger/service.py normalizes this into a Trade.
    external_id is the exchange's own trade/execution id, used to dedupe
    on repeated syncs. realized_pnl is None where the exchange doesn't
    report it per-fill (see each private client for which ones do)."""

    exchange: str
    external_id: str
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    realized_pnl: float | None
    order_id: str
    timestamp: float


class InvalidCredentialsError(Exception):
    """Raised by a PrivateExchangeClient when the exchange rejects the
    API key/secret (auth failure) - as opposed to a transient network
    error, which should propagate as-is."""
