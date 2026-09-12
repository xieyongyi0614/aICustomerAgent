"""架构 §6.2 十五类错误 + 附：逐行可执行断言（FEISHU-006 §6.1 收口）。

每行断言 4 个维度中可单测表达的子集；HTTP 维度由 tests/e2e/test_feishu_webhook.py
覆盖，重试维度由 tests/unit/test_feishu_delivery.py 覆盖，此处固化行 → 断言的映射。
"""

from datetime import datetime, timezone

import pytest

from app.channels.base import InboundMessage, OutboundMessage, RecipientRef
from app.channels.feishu import adapter, delivery
from app.channels.feishu.adapter import FALLBACK_TEXTS
from app.channels.feishu import client as feishu_client
from app.channels.feishu.delivery import FeishuChannelAdapter, send_proactive
from app.channels.feishu.errors import (
    FeishuAuthError,
    FeishuClientError,
    FeishuConfigError,
    FeishuDisabledError,
    FeishuRateLimitError,
    FeishuServerError,
    FeishuTimeoutError,
    classify,
)
from app.channels.feishu import events
from app.channels.feishu.identity import FEISHU_CHANNEL
from app.services import channel_identity_service
from app.services.agent_service import EmptyLLMResponseError


@pytest.fixture(autouse=True)
def _reset_state():
    events.reset_event_state()
    delivery.reset_delivery_state()
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()
    yield
    events.reset_event_state()
    delivery.reset_delivery_state()
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()


APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_mx",
    "feishu_app_secret": "secret-mx-value",
    "feishu_verification_token": "vtoken-mx",
}


@pytest.fixture(autouse=True)
def _enabled(override_settings):
    override_settings(**APP_SETTINGS)


@pytest.fixture(autouse=True)
def _default_ok_transport():
    class _Ok:
        async def post_json(self, url, body, timeout, headers=None):
            if "tenant_access_token" in url:
                return feishu_client.HttpResponse(
                    status=200,
                    json={"code": 0, "tenant_access_token": "t-mx", "expire": 7200},
                    raw_len=8,
                )
            return feishu_client.HttpResponse(
                status=200,
                json={"code": 0, "msg": "ok", "data": {"message_id": "om_mx_new"}},
                raw_len=8,
            )

    fake = _Ok()
    feishu_client.set_transport(fake)
    return fake


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    monkeypatch.setattr(adapter.llm_factory, "get_llm", lambda profile_id=None: object())


@pytest.fixture(autouse=True)
def _fake_retry_sleep(monkeypatch):
    sleeps = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    feishu_client._sleep = _sleep
    return sleeps


@pytest.fixture(autouse=True)
def _stub_identity(monkeypatch):
    from app.services.channel_identity_service import ResolvedIdentity

    def _resolve(channel, external_id, **kwargs):
        return ResolvedIdentity(
            channel=channel,
            external_id=external_id,
            internal_user_id=f"{channel}:{external_id}",
            session_id=f"{channel}:{external_id}",
            created=True,
        )

    monkeypatch.setattr(channel_identity_service, "resolve", _resolve)


def _inbound(open_id="ou_mx", reply_ref="om_mx"):
    return InboundMessage(
        channel="feishu",
        external_user_id=open_id,
        text="你好",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reply_ref=reply_ref,
        metadata={},
    )


def _mount_stream(monkeypatch, events_seq=None, exc=None):
    import asyncio

    calls = []

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        calls.append(content)
        if exc is not None:
            raise exc
        for event in events_seq or []:
            yield event

    _stream.calls = calls
    monkeypatch.setattr(adapter.agent_service, "stream_chat", _stream)
    return _stream


def _mount_transport(monkeypatch, status=None, code=99991400):
    class _Fake:
        def __init__(self):
            self.calls = []

        async def post_json(self, url, body, timeout, headers=None):
            self.calls.append(url)
            if "tenant_access_token" in url:
                payload = {"code": 0, "tenant_access_token": "t-x", "expire": 7200}
                return feishu_client.HttpResponse(status=200, json=payload, raw_len=8)
            return feishu_client.HttpResponse(
                status=status, json={"code": code, "msg": "err"}, raw_len=8
            )

    fake = _Fake()
    feishu_client.set_transport(fake)
    return fake


def _reply_message():
    return OutboundMessage(
        channel=FEISHU_CHANNEL,
        recipient=RecipientRef(channel=FEISHU_CHANNEL, external_id="ou_a"),
        text="hi",
        reply_ref="om_m",
    )


def test_row1_token_mismatch_is_auth_error_no_retry():
    with pytest.raises(FeishuAuthError):
        events.verify_token("forged", "expected")


def test_row1b_signature_mismatch_is_auth_error():
    with pytest.raises(FeishuAuthError):
        events.verify_signature(b"{}", "123", "n", "encrypt-key-x", "bad")


def test_row1c_timestamp_out_of_window_is_auth_error():
    events._now = lambda: 1_000_000.0
    with pytest.raises(FeishuAuthError):
        events.verify_signature(b"{}", "999000", "n", "encrypt-key-x", "sig")


def test_row2_decrypt_failure_is_config_error():
    with pytest.raises(FeishuConfigError):
        events.decrypt("wrong-key", "AAAA")


def test_row3_parse_failure_returns_none():
    assert events.parse_message_event({"header": {}}) is None
    assert events.parse_message_event({}) is None


def test_row4_inapplicable_events_return_none():
    payload = {
        "header": {"event_id": "e1", "event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_x"}},
            "message": {
                "message_id": "om",
                "chat_id": "oc",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text": "hi"}',
            },
        },
    }
    assert events.parse_message_event(payload) is None
    payload["event"]["message"]["chat_type"] = "p2p"
    payload["event"]["message"]["message_type"] = "image"
    assert events.parse_message_event(payload) is None


def test_row5_duplicate_event_accepted_once():
    assert events.accept_event("evt-mx") is True
    assert events.accept_event("evt-mx") is False


@pytest.mark.asyncio
async def test_row6_identity_failure_yields_fallback_and_skips_pipeline(monkeypatch):
    def _raise(channel, external_id, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(channel_identity_service, "resolve", _raise)
    stream = _mount_stream(monkeypatch, events_seq=[{"kind": "token", "text": "x"}])
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "identity_error"
    assert outcome.outbound_text == FALLBACK_TEXTS["identity_error"]
    assert stream.calls == []


@pytest.mark.asyncio
async def test_row7_pipeline_exception_yields_fallback(monkeypatch):
    stream = _mount_stream(monkeypatch, exc=ValueError("boom"))
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "pipeline_error"
    assert outcome.outbound_text == FALLBACK_TEXTS["pipeline_error"]
    assert len(stream.calls) == 1


@pytest.mark.asyncio
async def test_row8_empty_reply_yields_fallback(monkeypatch):
    stream = _mount_stream(
        monkeypatch, events_seq=[{"kind": "token", "text": " "}, {"kind": "done", "turn_id": "t"}]
    )
    outcome = await adapter.handle_inbound_message(_inbound())
    assert outcome.error_kind == "empty_response"
    assert outcome.outbound_text == FALLBACK_TEXTS["empty_response"]
    assert len(stream.calls) == 1


@pytest.mark.asyncio
async def test_row9_outbound_failure_retry_matrix(monkeypatch):
    retryable = [FeishuRateLimitError("op"), FeishuServerError("op"), FeishuTimeoutError("op")]
    non_retryable = [FeishuAuthError("op"), FeishuClientError("op"), FeishuConfigError("op")]
    for error in retryable:
        assert error.retryable is True
    for error in non_retryable:
        assert error.retryable is False
    fake = _mount_transport(monkeypatch, status=429)
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert len([c for c in fake.calls if "token" not in c]) == 3
    fake = _mount_transport(monkeypatch, status=400)
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert len([c for c in fake.calls if "token" not in c]) == 1


def test_row10_overlong_reply_is_split_losslessly():
    from app.channels.feishu.outbound import MAX_PARTS, normalize_text, split_text

    text = normalize_text("  " + "啊。" * 30 + "  ")
    parts = split_text(text, 8)
    assert "".join(parts) == text
    if len(parts) == MAX_PARTS:
        assert all(len(part) <= 8 for part in parts)


@pytest.mark.asyncio
async def test_row11_duplicate_delivery_not_doubled(monkeypatch):
    _mount_transport(monkeypatch, status=200, code=0)
    fake_adapter = FeishuChannelAdapter()
    first = await fake_adapter.send(_reply_message())
    second = await fake_adapter.send(_reply_message())
    assert first.ok and second.ok
    assert delivery._delivered
    assert len([k for k in delivery._delivered if k.startswith("reply:om_m")]) == 1


@pytest.mark.asyncio
async def test_row12_overload_rejects_latest_and_recovers(monkeypatch):
    adapter._session_load["feishu:ou_over"] = 99
    stream = _mount_stream(
        monkeypatch,
        events_seq=[{"kind": "token", "text": "x"}, {"kind": "done", "turn_id": "t"}],
    )
    outcome = await adapter.handle_inbound_message(_inbound(open_id="ou_over"))
    assert outcome.error_kind == "overloaded"
    assert outcome.outbound_text == FALLBACK_TEXTS["overloaded"]
    assert stream.calls == []
    adapter._session_load.clear()
    outcome = await adapter.handle_inbound_message(_inbound(open_id="ou_over"))
    assert outcome.error_kind is None


def test_row13_inbound_rate_limit_window(override_settings):
    override_settings(chat_rate_limit_per_minute=2)
    events._now = lambda: 5_000.0
    assert events.allow_rate("ou_rate_mx") is True
    assert events.allow_rate("ou_rate_mx") is True
    assert events.allow_rate("ou_rate_mx") is False
    assert events.allow_rate("ou_rate_other") is True


@pytest.mark.asyncio
async def test_row14_proactive_recipient_unresolved_no_request(monkeypatch):
    def _none(internal_user_id, channel):
        return None

    monkeypatch.setattr(channel_identity_service, "resolve_recipient", _none)
    fake = _mount_transport(monkeypatch, status=200, code=0)
    result = await send_proactive("feishu:ou_ghost", "hi", "k1")
    assert result.ok is False
    assert result.error.value == "not_found"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_row15_proactive_without_idempotency_key_rejected(monkeypatch):
    fake = _mount_transport(monkeypatch, status=200, code=0)
    result = await send_proactive("feishu:ou_x", "hi", "")
    assert result.ok is False
    assert result.error.value == "invalid_request"
    assert fake.calls == []


def test_extra_disabled_error_zero_path(override_settings):
    import asyncio

    override_settings(feishu_enabled=False)

    async def _call():
        await feishu_client.get_tenant_access_token()

    with pytest.raises(FeishuDisabledError):
        asyncio.run(_call())
    assert feishu_client._transport is None


def test_error_semantics_align_with_web_chat_three_classes():
    assert classify("op", 500, None).retryable is True
    assert isinstance(EmptyLLMResponseError("x"), Exception)
    assert FALLBACK_TEXTS["llm_error"] != FALLBACK_TEXTS["empty_response"]
    assert FALLBACK_TEXTS["empty_response"] != FALLBACK_TEXTS["pipeline_error"]
    for text in FALLBACK_TEXTS.values():
        assert "500" not in text and "Traceback" not in text
