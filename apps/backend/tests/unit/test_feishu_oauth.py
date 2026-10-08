"""飞书 OAuth 客户端单测：授权地址 / 换身份 / 错误映射 / 脱敏（假传输，零真实网络）。"""

from __future__ import annotations

import json
import urllib.parse

import pytest

from app.core.settings import get_settings
from app.services.identity.feishu import oauth as feishu_oauth
from app.services.identity.feishu.oauth import (
    FeishuOAuthCodeInvalid,
    FeishuOAuthError,
    UrllibFeishuOAuthClient,
)

pytestmark = pytest.mark.unit

APPS = "cli_test_app"
SECRET = "super-secret-value"
REDIRECT = "https://asuna.example.com/api/v1/auth/feishu/callback"
AUTHORIZE = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"


class FakeCall:
    def __init__(self, *, method, url, headers, body, timeout):
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.timeout = timeout

    def json_body(self) -> dict:
        return json.loads((self.body or b"{}").decode("utf-8"))


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[FakeCall] = []

    def request(self, *, method, url, headers, body, timeout):
        self.calls.append(
            FakeCall(method=method, url=url, headers=headers, body=body, timeout=timeout)
        )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _token_response(access_token: str = "u-abc", **extra) -> tuple:
    payload = {"code": 0, "access_token": access_token, "token_type": "Bearer"}
    payload.update(extra)
    return 200, json.dumps(payload).encode("utf-8")


def _identity_response(open_id: str = "ou_1") -> tuple:
    return 200, json.dumps(
        {
            "code": 0,
            "data": {"open_id": open_id, "union_id": "on_1", "tenant_key": "tk_1"},
        }
    ).encode("utf-8")


def _biz_error(biz_code: int, **extra) -> tuple:
    payload = {"code": biz_code, "msg": "boom"}
    payload.update(extra)
    return 200, json.dumps(payload).encode("utf-8")


@pytest.fixture
def oauth_env(override_settings):
    override_settings(
        feishu_enabled=False,
        feishu_app_id=APPS,
        feishu_app_secret=SECRET,
        feishu_oauth_redirect_uri=REDIRECT,
        feishu_oauth_authorize_url=AUTHORIZE,
        feishu_oauth_scope="",
        feishu_oauth_state_ttl_seconds=300,
        feishu_http_max_attempts=2,
        feishu_http_backoff_seconds=0.0,
        feishu_http_backoff_max_seconds=0.0,
        feishu_timeout_seconds=1.0,
    )


def _client(responses) -> tuple[UrllibFeishuOAuthClient, FakeTransport]:
    transport = FakeTransport(responses)
    return UrllibFeishuOAuthClient(transport), transport


def test_authorize_url_carries_required_params(oauth_env):
    client, _ = _client([])
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(client.authorize_url("st-1")).query
    )
    assert query["client_id"] == [APPS]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["state"] == ["st-1"]
    assert "scope" not in query


def test_authorize_url_includes_configured_scope(override_settings):
    override_settings(
        feishu_enabled=False,
        feishu_app_id=APPS,
        feishu_app_secret=SECRET,
        feishu_oauth_redirect_uri=REDIRECT,
        feishu_oauth_authorize_url=AUTHORIZE,
        feishu_oauth_scope="contact:user.base:readonly",
    )
    client, _ = _client([])
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(client.authorize_url("st-2")).query
    )
    assert query["scope"] == ["contact:user.base:readonly"]


async def test_exchange_code_posts_code_then_fetches_identity(oauth_env):
    client, transport = _client([_token_response(), _identity_response("ou_9")])

    identity = await client.exchange_code("one-time-code")

    assert identity.open_id == "ou_9"
    assert identity.union_id == "on_1"
    assert identity.tenant_key == "tk_1"
    token_call, info_call = transport.calls
    assert token_call.method == "POST"
    assert token_call.url.endswith(feishu_oauth.TOKEN_PATH)
    body = token_call.json_body()
    assert body["grant_type"] == "authorization_code"
    assert body["client_id"] == APPS
    assert body["client_secret"] == SECRET
    assert body["code"] == "one-time-code"
    assert body["redirect_uri"] == REDIRECT
    assert info_call.method == "GET"
    assert info_call.url.endswith(feishu_oauth.USER_INFO_PATH)
    assert info_call.headers["Authorization"] == "Bearer u-abc"


async def test_nested_token_shape_is_supported(oauth_env):
    nested = (200, json.dumps({"code": 0, "data": {"access_token": "u-nested"}}).encode())
    client, transport = _client([nested, _identity_response()])

    identity = await client.exchange_code("c")

    assert identity.open_id == "ou_1"
    assert transport.calls[1].headers["Authorization"] == "Bearer u-nested"


async def test_token_exchange_is_never_retried(oauth_env):
    client, transport = _client([TimeoutError("timed out")])

    with pytest.raises(FeishuOAuthError):
        await client.exchange_code("one-time-code")

    assert len(transport.calls) == 1


async def test_user_info_request_retries_then_succeeds(oauth_env):
    client, transport = _client(
        [_token_response(), TimeoutError("timed out"), _identity_response()]
    )

    identity = await client.exchange_code("c")

    assert identity.open_id == "ou_1"
    assert len(transport.calls) == 3


async def test_user_info_request_exhausts_attempts(oauth_env):
    client, transport = _client(
        [_token_response(), TimeoutError("t1"), TimeoutError("t2")]
    )

    with pytest.raises(FeishuOAuthError):
        await client.exchange_code("c")

    assert len(transport.calls) == 3


async def test_invalid_code_maps_to_code_invalid(oauth_env):
    client, transport = _client([_biz_error(20003)])

    with pytest.raises(FeishuOAuthCodeInvalid):
        await client.exchange_code("one-time-code")

    assert len(transport.calls) == 1


async def test_expired_code_maps_to_code_invalid(oauth_env):
    client, _ = _client([_biz_error(20004)])

    with pytest.raises(FeishuOAuthCodeInvalid):
        await client.exchange_code("c")


async def test_redirect_uri_mismatch_is_logged_as_config_error(oauth_env, caplog):
    client, _ = _client([_biz_error(20029)])

    with pytest.raises(FeishuOAuthError):
        await client.exchange_code("c")

    assert "FEISHU_OAUTH_REDIRECT_URI" in caplog.text


async def test_missing_open_id_is_rejected(oauth_env):
    client, _ = _client([_token_response(), (200, json.dumps({"code": 0, "data": {}}).encode())])

    with pytest.raises(FeishuOAuthError):
        await client.exchange_code("c")


async def test_missing_access_token_is_rejected(oauth_env):
    client, _ = _client([(200, json.dumps({"code": 0}).encode())])

    with pytest.raises(FeishuOAuthError):
        await client.exchange_code("c")


async def test_failures_never_leak_code_or_secret(oauth_env):
    client, _ = _client([_biz_error(20001), TimeoutError("down")])

    with pytest.raises(FeishuOAuthError) as first:
        await client.exchange_code("secret-code-value")
    assert SECRET not in str(first.value)
    assert "secret-code-value" not in str(first.value)

    with pytest.raises(FeishuOAuthError) as second:
        await client.exchange_code("secret-code-value")
    assert SECRET not in str(second.value)
    assert "secret-code-value" not in str(second.value)


async def test_non_json_response_is_rejected(oauth_env):
    client, _ = _client([(200, b"<html>gateway</html>")])

    with pytest.raises(FeishuOAuthError):
        await client.exchange_code("c")


def test_oauth_configured_requires_full_credentials(override_settings):
    override_settings(
        feishu_enabled=False,
        feishu_app_id=APPS,
        feishu_app_secret="",
        feishu_oauth_redirect_uri=REDIRECT,
    )
    assert get_settings().oauth_configured() is False

    override_settings(
        feishu_enabled=False,
        feishu_app_id=APPS,
        feishu_app_secret=SECRET,
        feishu_oauth_redirect_uri="",
    )
    assert get_settings().oauth_configured() is False

    override_settings(
        feishu_enabled=False,
        feishu_app_id=APPS,
        feishu_app_secret=SECRET,
        feishu_oauth_redirect_uri=REDIRECT,
    )
    assert get_settings().oauth_configured() is True


def test_oauth_configured_is_independent_of_channel_switch(override_settings):
    override_settings(
        feishu_enabled=True,
        feishu_instance_count=1,
        feishu_app_id=APPS,
        feishu_app_secret=SECRET,
        feishu_verification_token="verify",
        feishu_oauth_redirect_uri=REDIRECT,
    )
    assert get_settings().oauth_configured() is True


def test_oauth_client_singleton_is_overridable():
    original = feishu_oauth.get_oauth_client()
    fake = object()
    feishu_oauth.set_oauth_client(fake)
    try:
        assert feishu_oauth.get_oauth_client() is fake
    finally:
        feishu_oauth.set_oauth_client(original)
