from __future__ import annotations

from forge.accounts.private_clients.base import PrivateExchangeClient
from forge.accounts.private_clients.binance import BinancePrivateClient
from forge.accounts.private_clients.bitget import BitgetPrivateClient
from forge.accounts.private_clients.bybit import BybitPrivateClient
from forge.accounts.private_clients.okx import OKXPrivateClient

CLIENT_CLASSES: dict[str, type[PrivateExchangeClient]] = {
    "binance": BinancePrivateClient,
    "bybit": BybitPrivateClient,
    "bitget": BitgetPrivateClient,
    "okx": OKXPrivateClient,
}

__all__ = [
    "PrivateExchangeClient",
    "BinancePrivateClient",
    "BybitPrivateClient",
    "BitgetPrivateClient",
    "OKXPrivateClient",
    "CLIENT_CLASSES",
]
