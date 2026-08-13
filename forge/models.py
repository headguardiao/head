from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class PriceLevel:
    price: float
    qty: float


@dataclass
class OrderBookSnapshot:
    exchange: str
    symbol: str
    timestamp: float  # epoch seconds
    bids: list[PriceLevel]
    asks: list[PriceLevel]
    sequence: int = 0


@dataclass
class Trade:
    exchange: str
    symbol: str
    price: float
    qty: float
    side: Side  # aggressor side
    timestamp: float


@dataclass
class OpenInterest:
    exchange: str
    symbol: str
    value_usd: float
    timestamp: float


@dataclass
class FundingRate:
    exchange: str
    symbol: str
    rate: float
    next_funding_time: float
    timestamp: float


@dataclass
class Liquidation:
    exchange: str
    symbol: str
    side: Side
    price: float
    qty: float
    timestamp: float
