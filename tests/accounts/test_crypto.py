import pytest
from cryptography.fernet import Fernet

import forge.accounts.crypto as crypto


@pytest.fixture(autouse=True)
def reset_fernet_cache():
    crypto._fernet = None
    yield
    crypto._fernet = None


def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("FORGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    ciphertext = crypto.encrypt_secret("super-secret-api-key")
    assert ciphertext != "super-secret-api-key"
    assert crypto.decrypt_secret(ciphertext) == "super-secret-api-key"


def test_missing_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("FORGE_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError):
        crypto.encrypt_secret("x")


def test_decrypt_with_wrong_key_raises_value_error(monkeypatch):
    monkeypatch.setenv("FORGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    ciphertext = crypto.encrypt_secret("value")

    crypto._fernet = None
    monkeypatch.setenv("FORGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        crypto.decrypt_secret(ciphertext)
