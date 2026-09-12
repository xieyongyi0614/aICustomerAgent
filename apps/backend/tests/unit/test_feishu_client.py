import asyncio
import logging
import time
import urllib.error

import pytest

from app.channels.feishu import client as feishu_client
from app.channels.feishu.client import (
    get_tenant_access_token,
    reset_feishu_client,
    set_transport,
    token_view,
)
from app.channels.feishu.errors import (
    FeishuAuthError,
    FeishuClientError,
    FeishuConfigError,
    FeishuDisabledError,
    FeishuRateLimitError,
    FeishuServerError,
    FeishuTimeoutError,
)

TOKEN_URL_PATH = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
CLIENT_LOGGER = "app.channels.feishu.client"

ENABLED_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_app",
    "feishu_app_secret": "super-secret-value",
    "feishu_verification_token": "verification-value",
}


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeTransport:
    def __init__(self, responses=None, exceptions=None, delay=0.0):
        self.calls = []
        self._responses = list(responses or [])
        self._exceptions = list(exceptions or [])
        self._delay = delay

    async def post_json(self, url, body, timeout):
        self.calls.append({"url": url, "body": dict(body), "timeout": timeout})
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exceptions:
            raise self._exceptions.pop(0)
        response = self._responses.pop(0)
        return feishu_client.HttpResponse(
            status=response["status"],
            json=response.get("json"),
            raw_len=response.get("raw_len", 0),
        )


def token_body(token="t-token-value", expire=7200, code=0):
    return {"code": code, "msg": "ok", "tenant_access_token": token, "expire": expire}


def ok_response(token="t-token-value", expire=7200, code=0):
    return {"status": 200, "json": token_body(token=token, expire=expire, code=code)}


def error_status(status):
    return {"status": status, "json": {"code": 99991400, "msg": "boom"}}


@pytest.fixture(autouse=True)
def _reset_client():
    reset_feishu_client()
    yield
    reset_feishu_client()


@pytest.fixture
def enabled(override_settings):
    def _apply(**extra):
        override_settings(**{**ENABLED_SETTINGS, **extra})

    return _apply


@pytest.fixture
def fake_clock():
    clock = FakeClock()
    feishu_client._clock = clock
    return clock


@pytest.fixture
def fake_sleep():
    sleeps = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    feishu_client._sleep = _sleep
    return sleeps


@pytest.mark.asyncio
async def test_first_fetch_returns_token(enabled):
    enabled()
    fake = FakeTransport([ok_response()])
    set_transport(fake)
    token = await get_tenant_access_token()
    assert token == "t-token-value"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"] == TOKEN_URL_PATH
    assert call["body"] == {"app_id": "cli_app", "app_secret": "super-secret-value"}
    assert call["timeout"] == 10.0


@pytest.mark.asyncio
async def test_cache_hit_does_not_refetch(enabled):
    enabled()
    fake = FakeTransport([ok_response()])
    set_transport(fake)
    first = await get_tenant_access_token()
    second = await get_tenant_access_token()
    assert first == second == "t-token-value"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_refresh_triggers_after_soft_line(enabled, fake_clock):
    enabled()
    fake = FakeTransport([ok_response(token="t-first"), ok_response(token="t-second")])
    set_transport(fake)
    assert await get_tenant_access_token() == "t-first"
    fake_clock.advance(7200 * 0.8 + 1)
    assert await get_tenant_access_token() == "t-second"
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_no_refresh_before_soft_line(enabled, fake_clock):
    enabled()
    fake = FakeTransport([ok_response()])
    set_transport(fake)
    await get_tenant_access_token()
    fake_clock.advance(7200 * 0.8 - 1)
    await get_tenant_access_token()
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_refresh_at_hard_expiry(enabled, fake_clock):
    enabled()
    fake = FakeTransport([ok_response(token="t-old"), ok_response(token="t-new")])
    set_transport(fake)
    await get_tenant_access_token()
    fake_clock.advance(7200 + 1)
    assert await get_tenant_access_token() == "t-new"
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_degraded_refresh_failure_reuses_old_token(enabled, fake_clock, caplog):
    enabled(feishu_http_max_attempts=1)
    fake = FakeTransport(
        [ok_response(token="t-old"), error_status(500)]
    )
    set_transport(fake)
    await get_tenant_access_token()
    fake_clock.advance(7200 * 0.8 + 1)
    with caplog.at_level(logging.WARNING, logger=CLIENT_LOGGER):
        token = await get_tenant_access_token()
    assert token == "t-old"
    assert len(fake.calls) == 2
    assert any("degraded" in r.getMessage() for r in caplog.records)
    assert token_view().has_token is True


@pytest.mark.asyncio
async def test_hard_expired_refresh_failure_raises_and_clears(enabled, fake_clock):
    enabled(feishu_http_max_attempts=1)
    fake = FakeTransport([ok_response(token="t-old"), error_status(500)])
    set_transport(fake)
    await get_tenant_access_token()
    fake_clock.advance(7200 + 1)
    with pytest.raises(FeishuServerError):
        await get_tenant_access_token()
    assert token_view().has_token is False


@pytest.mark.asyncio
async def test_single_flight_ten_concurrent_one_request(enabled):
    enabled()
    fake = FakeTransport([ok_response()], delay=0.05)
    set_transport(fake)
    results = await asyncio.gather(
        *[get_tenant_access_token() for _ in range(10)]
    )
    assert len(fake.calls) == 1
    assert len(set(results)) == 1
    assert results[0] == "t-token-value"


@pytest.mark.asyncio
async def test_disabled_raises_before_transport_construction(override_settings):
    override_settings(feishu_enabled=False)
    with pytest.raises(FeishuDisabledError):
        await get_tenant_access_token()
    assert feishu_client._transport is None


@pytest.mark.asyncio
async def test_disabled_zero_network_even_with_injected_transport(override_settings):
    override_settings(feishu_enabled=False)
    fake = FakeTransport([ok_response()])
    set_transport(fake)
    with pytest.raises(FeishuDisabledError):
        await get_tenant_access_token()
    assert len(fake.calls) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error_type", [(429, FeishuRateLimitError), (500, FeishuServerError), (503, FeishuServerError)])
async def test_retryable_statuses_retry_to_limit(enabled, fake_sleep, status, error_type):
    enabled(
        feishu_http_max_attempts=4,
        feishu_http_backoff_seconds=0.5,
        feishu_http_backoff_max_seconds=8.0,
    )
    fake = FakeTransport([error_status(status)] * 4)
    set_transport(fake)
    with pytest.raises(error_type):
        await get_tenant_access_token()
    assert len(fake.calls) == 4
    assert fake_sleep == [0.5, 1.0, 2.0]


@pytest.mark.asyncio
async def test_retryable_transport_exception_retries(enabled, fake_sleep):
    enabled(feishu_http_max_attempts=3)
    fake = FakeTransport(exceptions=[urllib.error.URLError("refused")] * 3)
    set_transport(fake)
    with pytest.raises(FeishuTimeoutError):
        await get_tenant_access_token()
    assert len(fake.calls) == 3
    assert fake_sleep == [0.5, 1.0]


@pytest.mark.asyncio
async def test_backoff_capped_at_max(enabled, fake_sleep):
    enabled(
        feishu_http_max_attempts=3,
        feishu_http_backoff_seconds=3.0,
        feishu_http_backoff_max_seconds=4.0,
    )
    fake = FakeTransport([error_status(500)] * 3)
    set_transport(fake)
    with pytest.raises(FeishuServerError):
        await get_tenant_access_token()
    assert fake_sleep == [3.0, 4.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,error_type", [(400, FeishuClientError), (401, FeishuAuthError), (403, FeishuAuthError), (404, FeishuClientError)])
async def test_non_retryable_statuses_fail_fast(enabled, fake_sleep, status, error_type):
    enabled()
    fake = FakeTransport([error_status(status)])
    set_transport(fake)
    with pytest.raises(error_type):
        await get_tenant_access_token()
    assert len(fake.calls) == 1
    assert fake_sleep == []


@pytest.mark.asyncio
async def test_retry_then_success_no_error_log(enabled, fake_sleep, caplog):
    enabled(feishu_http_max_attempts=3)
    fake = FakeTransport([error_status(429), ok_response()])
    set_transport(fake)
    with caplog.at_level(logging.INFO, logger=CLIENT_LOGGER):
        token = await get_tenant_access_token()
    assert token == "t-token-value"
    assert len(fake.calls) == 2
    assert fake_sleep == [0.5]
    client_records = [r for r in caplog.records if r.name == CLIENT_LOGGER]
    assert not [r for r in client_records if r.levelno >= logging.ERROR]
    assert [r for r in client_records if r.levelno == logging.WARNING]


@pytest.mark.asyncio
async def test_2xx_auth_business_code_not_cached(enabled):
    enabled()
    fake = FakeTransport([ok_response(code=10003)])
    set_transport(fake)
    with pytest.raises(FeishuAuthError):
        await get_tenant_access_token()
    assert len(fake.calls) == 1
    assert token_view().has_token is False


@pytest.mark.asyncio
async def test_2xx_generic_business_code_client_error(enabled):
    enabled()
    fake = FakeTransport([ok_response(code=99991400)])
    set_transport(fake)
    with pytest.raises(FeishuClientError):
        await get_tenant_access_token()
    assert token_view().has_token is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "msg": "ok"},
        {"code": 0, "msg": "ok", "tenant_access_token": "t-x"},
        {"code": 0, "msg": "ok", "tenant_access_token": "t-x", "expire": 0},
        {"code": 0, "msg": "ok", "tenant_access_token": "", "expire": 7200},
    ],
)
async def test_invalid_structure_not_cached(enabled, payload):
    enabled()
    fake = FakeTransport([{"status": 200, "json": payload}])
    set_transport(fake)
    with pytest.raises(FeishuConfigError):
        await get_tenant_access_token()
    assert token_view().has_token is False


@pytest.mark.asyncio
async def test_non_json_body_config_error(enabled):
    enabled()
    fake = FakeTransport([{"status": 200, "json": None, "raw_len": 12}])
    set_transport(fake)
    with pytest.raises(FeishuConfigError):
        await get_tenant_access_token()
    assert token_view().has_token is False


@pytest.mark.asyncio
async def test_failures_never_leak_secrets_or_token(enabled, caplog):
    enabled(
        feishu_app_secret="super-secret-value",
        feishu_verification_token="verification-value",
        feishu_encrypt_key="",
        feishu_http_max_attempts=2,
    )
    fake = FakeTransport([error_status(500), error_status(500)])
    set_transport(fake)
    with caplog.at_level(logging.INFO, logger=CLIENT_LOGGER):
        with pytest.raises(FeishuServerError) as exc_info:
            await get_tenant_access_token()
    text = caplog.text
    assert "super-secret-value" not in text
    assert "t-token-value" not in text
    assert str(exc_info.value).find("super-secret-value") == -1
    assert all("super-secret-value" not in str(arg) for arg in exc_info.value.args)


def test_scrub_replaces_secrets():
    scrubbed = feishu_client._scrub(
        "body has super-secret-value inside", ("super-secret-value", "verification-value")
    )
    assert scrubbed == "body has <redacted> inside"


@pytest.mark.asyncio
async def test_token_view_fields_and_no_token_value(enabled, fake_clock):
    assert set(token_view().__dataclass_fields__) == {
        "has_token",
        "needs_refresh",
        "expires_in",
        "age_seconds",
    }
    empty = token_view()
    assert empty.has_token is False
    assert empty.needs_refresh is True
    assert empty.expires_in is None
    assert empty.age_seconds is None
    enabled()
    set_transport(FakeTransport([ok_response(expire=7200)]))
    await get_tenant_access_token()
    view = token_view()
    assert view.has_token is True
    assert view.needs_refresh is False
    assert view.expires_in == 7200
    assert view.age_seconds == 0.0
    assert "t-token-value" not in str(view)


@pytest.mark.asyncio
async def test_reset_feishu_client_clears_all_state(enabled, fake_clock):
    enabled()
    set_transport(FakeTransport([ok_response()]))
    await get_tenant_access_token()
    reset_feishu_client()
    assert token_view().has_token is False
    assert feishu_client._transport is None
    assert feishu_client._token_lock is None
    assert feishu_client._clock is time.monotonic
