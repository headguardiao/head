import base64

from forge.accounts.private_clients.bitget import BitgetPrivateClient


def _client(secret="api-secret", passphrase="pass"):
    return BitgetPrivateClient("api-key", secret, passphrase, http=None)


def test_signature_is_deterministic():
    c = _client()
    sig1 = c._sign("1700000000000", "GET", "/api/v2/mix/account/accounts?productType=USDT-FUTURES")
    sig2 = c._sign("1700000000000", "GET", "/api/v2/mix/account/accounts?productType=USDT-FUTURES")
    assert sig1 == sig2


def test_signature_changes_with_request_path():
    c = _client()
    a = c._sign("1700000000000", "GET", "/api/v2/mix/account/accounts")
    b = c._sign("1700000000000", "GET", "/api/v2/mix/position/all-position")
    assert a != b


def test_signature_is_valid_base64_sha256_digest():
    signature = _client()._sign("1700000000000", "GET", "/api/v2/mix/account/accounts")
    decoded = base64.b64decode(signature)
    assert len(decoded) == 32  # SHA-256 digest size
