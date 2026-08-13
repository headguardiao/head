from forge.normalizer import canonical_from_exchange, exchange_symbol, notional_usd


def test_notional_usd():
    assert notional_usd(100, 2) == 200
    assert notional_usd(100, 2, contract_multiplier=0.01) == 2.0


def test_symbol_roundtrip():
    for exchange in ("binance", "okx", "bybit", "bitget"):
        ex_symbol = exchange_symbol("BTCUSDT", exchange)
        assert canonical_from_exchange(exchange, ex_symbol) == "BTCUSDT"


def test_unknown_symbol_returns_none():
    assert canonical_from_exchange("binance", "DOESNOTEXIST") is None
