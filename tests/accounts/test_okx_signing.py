import base64

from forge.accounts.private_clients.okx import OKXPrivateClient


def _client(secret="api-secret", passphrase="pass"):
    return OKXPrivateClient("api-key", secret, passphrase, http=None)


def test_signature_is_deterministic():
    c = _client()
    sig1 = c._sign("2026-08-14T00:00:00.000Z", "GET", "/api/v5/account/balance")
    sig2 = c._sign("2026-08-14T00:00:00.000Z", "GET", "/api/v5/account/balance")
    assert sig1 == sig2


def test_signature_changes_with_secret():
    a = _client(secret="secret-a")._sign("2026-08-14T00:00:00.000Z", "GET", "/api/v5/account/balance")
    b = _client(secret="secret-b")._sign("2026-08-14T00:00:00.000Z", "GET", "/api/v5/account/balance")
    assert a != b


def test_signature_is_valid_base64_sha256_digest():
    signature = _client()._sign("2026-08-14T00:00:00.000Z", "GET", "/api/v5/account/balance")
    decoded = base64.b64decode(signature)
    assert len(decoded) == 32


def test_timestamp_format_is_iso8601_with_z_suffix():
    ts = _client()._timestamp()
    assert ts.endswith("Z")
    assert "T" in ts
