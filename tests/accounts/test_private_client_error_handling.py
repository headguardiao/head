"""Regression coverage for the bug found via the browser dashboard: a
non-auth API error (e.g. Binance rate-limiting the IP) was falling through
_signed_get() as if it were a normal payload, and get_balance() then
crashed with an opaque TypeError while iterating it instead of raising a
clear error. Every private client should turn ANY API error response into
either InvalidCredentialsError (auth problems) or RuntimeError (everything
else) - never let it reach the payload-parsing code."""

import pytest

from forge.accounts.models import InvalidCredentialsError
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


@pytest.mark.parametrize(
    "client_cls, auth_status, auth_payload, rate_limit_payload, success_payload",
    [
        (
            BinancePrivateClient,
            401,
            {"code": -2014, "msg": "API-key format invalid."},
            {"code": -1003, "msg": "Too many requests"},
            [{"balance": "100", "availableBalance": "90"}],
        ),
        (
            BybitPrivateClient,
            200,
            {"retCode": 10003, "retMsg": "invalid api key"},
            {"retCode": 10006, "retMsg": "too many visits"},
            {"retCode": 0, "retMsg": "OK", "result": {"list": [{"totalEquity": "100", "totalAvailableBalance": "90"}]}},
        ),
        (
            BitgetPrivateClient,
            200,
            {"code": "40037", "msg": "apikey not exist"},
            {"code": "429000", "msg": "too many requests"},
            {"code": "00000", "msg": "success", "data": [{"usdtEquity": "100", "available": "90"}]},
        ),
        (
            OKXPrivateClient,
            200,
            {"code": "50111", "msg": "invalid OK-ACCESS-KEY"},
            {"code": "50011", "msg": "rate limit reached"},
            {"code": "0", "msg": "", "data": [{"totalEq": "100", "availEq": "90"}]},
        ),
    ],
)
class TestPrivateClientErrorHandling:
    def _client(self, client_cls, http):
        return client_cls("api-key", "api-secret", "passphrase", http)

    async def test_auth_error_raises_invalid_credentials(
        self, client_cls, auth_status, auth_payload, rate_limit_payload, success_payload
    ):
        client = self._client(client_cls, _FakeHttp(auth_status, auth_payload))
        with pytest.raises(InvalidCredentialsError):
            await client.get_balance()

    async def test_non_auth_api_error_raises_runtime_error_not_type_error(
        self, client_cls, auth_status, auth_payload, rate_limit_payload, success_payload
    ):
        # A rate-limit-shaped error dict must not be silently treated as a
        # normal payload and crash while being parsed as balances.
        client = self._client(client_cls, _FakeHttp(200, rate_limit_payload))
        with pytest.raises(RuntimeError):
            await client.get_balance()

    async def test_success_payload_parses_without_raising(
        self, client_cls, auth_status, auth_payload, rate_limit_payload, success_payload
    ):
        client = self._client(client_cls, _FakeHttp(200, success_payload))
        balance = await client.get_balance()
        assert balance.total_equity_usd == 100.0
        assert balance.available_usd == 90.0

    async def test_empty_body_401_raises_invalid_credentials_not_attribute_error(
        self, client_cls, auth_status, auth_payload, rate_limit_payload, success_payload
    ):
        # Found live via the dashboard: Bybit returns HTTP 401 with an
        # EMPTY body for some malformed-auth requests. aiohttp's .json()
        # turns that into None, and blindly calling .get() on it before
        # checking the status crashed with AttributeError instead of the
        # intended InvalidCredentialsError.
        client = self._client(client_cls, _FakeHttp(401, None))
        with pytest.raises(InvalidCredentialsError):
            await client.get_balance()

    async def test_empty_body_200_raises_runtime_error_not_attribute_error(
        self, client_cls, auth_status, auth_payload, rate_limit_payload, success_payload
    ):
        client = self._client(client_cls, _FakeHttp(200, None))
        with pytest.raises(RuntimeError):
            await client.get_balance()
