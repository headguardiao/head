from forge.accounts.private_clients.binance import BinancePrivateClient


def _client(secret="api-secret"):
    return BinancePrivateClient("api-key", secret, None, http=None)


def test_signature_is_deterministic():
    query = "symbol=BTCUSDT&timestamp=1700000000000&recvWindow=5000"
    assert _client()._sign(query) == _client()._sign(query)


def test_signature_changes_with_query():
    a = _client()._sign("symbol=BTCUSDT&timestamp=1700000000000")
    b = _client()._sign("symbol=ETHUSDT&timestamp=1700000000000")
    assert a != b


def test_signature_changes_with_secret():
    query = "symbol=BTCUSDT&timestamp=1700000000000"
    assert _client("secret-a")._sign(query) != _client("secret-b")._sign(query)


def test_signature_is_64_char_hex():
    signature = _client()._sign("symbol=BTCUSDT&timestamp=1700000000000")
    assert len(signature) == 64
    int(signature, 16)  # raises ValueError if not valid hex
