from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SymbolMap:
    canonical: str
    binance: str
    okx: str
    bybit: str
    bitget: str


# Canonical symbol -> per-exchange instrument id. Extend this table when
# adding symbols or expansion-tier exchanges (Gate.io, KuCoin, MEXC, ...).
SYMBOLS: dict[str, SymbolMap] = {
    "BTCUSDT": SymbolMap("BTCUSDT", "BTCUSDT", "BTC-USDT-SWAP", "BTCUSDT", "BTCUSDT"),
    "ETHUSDT": SymbolMap("ETHUSDT", "ETHUSDT", "ETH-USDT-SWAP", "ETHUSDT", "ETHUSDT"),
}

_REVERSE: dict[tuple[str, str], str] = {}
for _canonical, _m in SYMBOLS.items():
    for _exchange in ("binance", "okx", "bybit", "bitget"):
        _REVERSE[(_exchange, getattr(_m, _exchange))] = _canonical


def exchange_symbol(canonical: str, exchange: str) -> str:
    return getattr(SYMBOLS[canonical], exchange)


def canonical_from_exchange(exchange: str, exchange_symbol_value: str) -> str | None:
    return _REVERSE.get((exchange, exchange_symbol_value))


def notional_usd(price: float, qty: float, contract_multiplier: float = 1.0) -> float:
    """USD notional for an order-book level or trade.

    The four core exchanges quote BTCUSDT/ETHUSDT perpetuals as linear
    USDT contracts with multiplier 1 (qty already in base-asset units),
    so this is price*qty by default. Pass a multiplier for symbols/
    exchanges that quote in contracts instead of coins (see PDF section
    5: never sum raw contract quantities across exchanges directly).
    """
    return price * qty * contract_multiplier
