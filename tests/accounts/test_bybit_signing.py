from forge.accounts.private_clients.bybit import BybitPrivateClient


def _client(api_key="api-key", secret="api-secret"):
    return BybitPrivateClient(api_key, secret, None, http=None)


def test_signature_is_deterministic():
    c = _client()
    assert c._sign("1700000000000", "accountType=UNIFIED") == c._sign("1700000000000", "accountType=UNIFIED")


def test_signature_changes_with_api_key():
    a = _client(api_key="key-a")._sign("1700000000000", "accountType=UNIFIED")
    b = _client(api_key="key-b")._sign("1700000000000", "accountType=UNIFIED")
    assert a != b


def test_signature_changes_with_timestamp():
    c = _client()
    a = c._sign("1700000000000", "accountType=UNIFIED")
    b = c._sign("1700000000001", "accountType=UNIFIED")
    assert a != b


def test_signature_is_64_char_hex():
    signature = _client()._sign("1700000000000", "accountType=UNIFIED")
    assert len(signature) == 64
    int(signature, 16)
