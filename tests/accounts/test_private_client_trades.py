"""Happy-path get_recent_trades() coverage per exchange, since each one
reports realized PnL (or doesn't) in a different shape - this is the
field mapping forge/ledger/service.py depends on to compute gross/net PnL."""

from forge.accounts.private_clients.binance import BinancePrivateClient
from forge.accounts.private_clients.bitget import BitgetPrivateClient
from forge.accounts.private_clients.bybit import BybitPrivateClient
from forge.accounts.private_clients.okx import OKXPrivateClient


class _FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeHttp:
    def __init__(self, status, payload):
        self._status = status
        self._payload = payload

    def get(self, url, headers=None):
        return _FakeResponse(self._status, self._payload)


async def test_binance_recent_trades_maps_realized_pnl_per_known_symbol():
    payload = [
        {
            "id": 123,
            "orderId": 111,
            "symbol": "BTCUSDT",
            "price": "50000.0",
            "qty": "0.1",
            "commission": "0.5",
            "realizedPnl": "10.0",
            "side": "BUY",
            "time": 1700000000000,
        }
    ]
    client = BinancePrivateClient("k", "s", None, _FakeHttp(200, payload))
    fills = await client.get_recent_trades()
    # one call per known symbol (config.settings.SYMBOLS = BTCUSDT, ETHUSDT) -
    # the fake returns the same payload for both, so 2 fills come back,
    # each tagged with the symbol its own request loop iteration was for.
    assert {f.symbol for f in fills} == {"BTCUSDT", "ETHUSDT"}
    assert len(fills) == 2
    assert fills[0].external_id == "123"
    assert fills[0].realized_pnl == 10.0
    assert fills[0].fee == 0.5


async def test_bybit_recent_trades_maps_closed_pnl():
    payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "execId": "exec-1",
                    "symbol": "BTCUSDT",
                    "side": "Buy",
                    "execQty": "0.1",
                    "execPrice": "50000.0",
                    "execFee": "0.5",
                    "closedPnl": "10.0",
                    "orderId": "order-1",
                    "execTime": "1700000000000",
                }
            ]
        },
    }
    client = BybitPrivateClient("k", "s", None, _FakeHttp(200, payload))
    fills = await client.get_recent_trades()
    assert len(fills) == 1
    assert fills[0].symbol == "BTCUSDT"
    assert fills[0].side == "BUY"
    assert fills[0].realized_pnl == 10.0


async def test_bybit_recent_trades_skips_symbols_outside_the_known_map():
    payload = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "execId": "1",
                    "symbol": "DOGEUSDT",
                    "side": "Buy",
                    "execQty": "1",
                    "execPrice": "1",
                    "execFee": "0",
                    "closedPnl": "0",
                    "orderId": "o",
                    "execTime": "1700000000000",
                }
            ]
        },
    }
    client = BybitPrivateClient("k", "s", None, _FakeHttp(200, payload))
    assert await client.get_recent_trades() == []


async def test_bitget_recent_trades_maps_profit_and_abs_fee():
    payload = {
        "code": "00000",
        "msg": "success",
        "data": {
            "fillList": [
                {
                    "tradeId": "trade-1",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "baseVolume": "0.1",
                    "price": "50000.0",
                    "fee": "-0.5",
                    "profit": "10.0",
                    "orderId": "order-1",
                    "cTime": "1700000000000",
                }
            ]
        },
    }
    client = BitgetPrivateClient("k", "s", "pass", _FakeHttp(200, payload))
    fills = await client.get_recent_trades()
    assert len(fills) == 1
    assert fills[0].symbol == "BTCUSDT"
    assert fills[0].fee == 0.5
    assert fills[0].realized_pnl == 10.0


async def test_okx_recent_trades_has_no_realized_pnl_and_maps_canonical_symbol():
    payload = {
        "code": "0",
        "msg": "",
        "data": [
            {
                "tradeId": "trade-1",
                "instId": "BTC-USDT-SWAP",
                "side": "buy",
                "fillSz": "0.1",
                "fillPx": "50000.0",
                "fee": "-0.5",
                "ordId": "order-1",
                "ts": "1700000000000",
            }
        ],
    }
    client = OKXPrivateClient("k", "s", "pass", _FakeHttp(200, payload))
    fills = await client.get_recent_trades()
    assert len(fills) == 1
    assert fills[0].symbol == "BTCUSDT"
    assert fills[0].fee == 0.5
    assert fills[0].realized_pnl is None
