import asyncio
import json
import logging

import pytest

from app.channels.base import ChannelErrorKind, OutboundMessage, RecipientRef, SendResult
from app.channels.feishu import client as feishu_client
from app.channels.feishu import delivery
from app.channels.feishu.delivery import (
    FeishuChannelAdapter,
    deliver_reply,
    send_proactive,
)
from app.channels.feishu.outbound import split_text
from app.services.identity import channel as channel_identity_service

TOKEN_URL_PART = "tenant_access_token"
VERIFICATION = "vtoken-dlv"
APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_dlv",
    "feishu_app_secret": "secret-dlv-value",
    "feishu_verification_token": VERIFICATION,
}

SUCCESS_BODY = {"code": 0, "msg": "ok", "data": {"message_id": "om_new_msg"}}


class FakeTransport:
    def __init__(self, responder):
        self.calls = []
        self._responder = responder

    async def post_json(self, url, body, timeout, headers=None):
        self.calls.append(
            {"url": url, "body": dict(body), "timeout": timeout, "headers": dict(headers or {})}
        )
        status, payload = self._responder(url, body)
        return feishu_client.HttpResponse(status=status, json=payload, raw_len=64)


def _token_body():
    return {"code": 0, "msg": "ok", "tenant_access_token": "t-dlv-token", "expire": 7200}


def _is_token_call(url):
    return TOKEN_URL_PART in url


@pytest.fixture(autouse=True)
def _reset_state(override_settings):
    override_settings(**APP_SETTINGS)
    feishu_client.reset_feishu_client()
    yield
    feishu_client.reset_feishu_client()


@pytest.fixture
def fake_sleep():
    sleeps = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    feishu_client._sleep = _sleep
    return sleeps


def _mount(monkeypatch, responder):
    fake = FakeTransport(responder)
    feishu_client.set_transport(fake)
    return fake


def _im_calls(fake):
    return [call for call in fake.calls if not _is_token_call(call["url"])]


def _reply_message():
    return OutboundMessage(
        channel="feishu",
        recipient=RecipientRef(channel="feishu", external_id="ou_a"),
        text="你好",
        reply_ref="om_src_1",
    )


def _proactive_message(external_id="ou_a", key="k1", text="在吗"):
    return OutboundMessage(
        channel="feishu",
        recipient=RecipientRef(channel="feishu", external_id=external_id),
        text=text,
        reply_ref=None,
        idempotency_key=key,
    )


def _ok_responder(url, body):
    if _is_token_call(url):
        return 200, _token_body()
    return 200, SUCCESS_BODY


def _status_responder(status, code=99991400):
    def _respond(url, body):
        if _is_token_call(url):
            return 200, _token_body()
        return status, {"code": code, "msg": "err"}

    return _respond


@pytest.mark.asyncio
async def test_reply_form_calls_reply_api(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is True
    im_calls = _im_calls(fake)
    assert len(im_calls) == 1
    assert "/reply" in im_calls[0]["url"]
    assert "om_src_1" in im_calls[0]["url"]
    assert im_calls[0]["body"]["msg_type"] == "text"
    assert im_calls[0]["body"]["content"] == json.dumps({"text": "你好"}, ensure_ascii=False)
    assert im_calls[0]["headers"]["Authorization"].startswith("Bearer ")
    assert result.external_message_id == "om_new_msg"


@pytest.mark.asyncio
async def test_proactive_form_calls_send_api_with_resolved_recipient(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    result = await FeishuChannelAdapter().send(_proactive_message(external_id="ou_resolved"))
    assert result.ok is True
    im_calls = _im_calls(fake)
    assert len(im_calls) == 1
    assert "receive_id_type=open_id" in im_calls[0]["url"]
    assert "/reply" not in im_calls[0]["url"]
    assert im_calls[0]["body"]["receive_id"] == "ou_resolved"


@pytest.mark.asyncio
async def test_proactive_without_idempotency_key_rejected(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    message = OutboundMessage(
        channel="feishu",
        recipient=RecipientRef(channel="feishu", external_id="ou_a"),
        text="hi",
        reply_ref=None,
        idempotency_key=None,
    )
    result = await FeishuChannelAdapter().send(message)
    assert result.ok is False
    assert result.error == ChannelErrorKind.INVALID_REQUEST
    assert fake.calls == []


@pytest.mark.asyncio
async def test_proactive_blank_idempotency_key_rejected(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    result = await FeishuChannelAdapter().send(_proactive_message(key="   "))
    assert result.ok is False
    assert fake.calls == []


@pytest.mark.asyncio
async def test_reply_runtime_failure_does_not_switch_to_send(monkeypatch):
    fake = _mount(monkeypatch, _status_responder(403))
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert result.error == ChannelErrorKind.AUTH
    urls = [call["url"] for call in _im_calls(fake)]
    assert urls and all("/reply" in url for url in urls)


@pytest.mark.asyncio
async def test_resolve_failure_proactive_no_request(monkeypatch):
    def _none(internal_user_id, channel):
        return None

    monkeypatch.setattr(channel_identity_service, "resolve_recipient", _none)
    fake = _mount(monkeypatch, _ok_responder)
    result = await send_proactive("feishu:ou_ghost", "hi", "k1")
    assert result.ok is False
    assert result.error == ChannelErrorKind.NOT_FOUND
    assert fake.calls == []


@pytest.mark.asyncio
async def test_send_proactive_uses_resolved_external_id(monkeypatch):
    seen = {}

    def _resolve(internal_user_id, channel):
        seen["input"] = (internal_user_id, channel)
        return RecipientRef(channel="feishu", external_id="ou_from_table")

    monkeypatch.setattr(channel_identity_service, "resolve_recipient", _resolve)
    fake = _mount(monkeypatch, _ok_responder)
    result = await send_proactive("feishu:ou_from_table", "在吗", "k1")
    assert result.ok is True
    assert seen["input"] == ("feishu:ou_from_table", "feishu")
    im_calls = _im_calls(fake)
    assert im_calls[0]["body"]["receive_id"] == "ou_from_table"


@pytest.mark.asyncio
async def test_long_text_split_into_sequential_requests(monkeypatch):
    monkeypatch.setenv("FEISHU_MAX_REPLY_CHARS", "5")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        recorded = []
        state = {"n": 0}

        def _respond(url, body):
            if _is_token_call(url):
                return 200, _token_body()
            state["n"] += 1
            recorded.append(json.loads(body["content"])["text"])
            return 200, {**SUCCESS_BODY, "data": {"message_id": f"om_{state['n']}"}}

        fake = _mount(monkeypatch, _respond)
        long_text = "啊。" * 10
        result = await FeishuChannelAdapter().send(
            OutboundMessage(
                channel="feishu",
                recipient=RecipientRef(channel="feishu", external_id="ou_a"),
                text=long_text,
                reply_ref="om_long",
            )
        )
        assert result.ok is True
        parts = split_text(long_text, 5)
        assert len(_im_calls(fake)) == len(parts)
        assert recorded == parts
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_empty_text_skipped(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    for text in ("", "   ", "\n\t "):
        result = await FeishuChannelAdapter().send(_proactive_message(text=text))
        assert result.ok is False
        assert result.error == ChannelErrorKind.INVALID_REQUEST
    assert fake.calls == []


@pytest.mark.asyncio
async def test_retryable_business_code_retries(monkeypatch, fake_sleep):
    fake = _mount(monkeypatch, _status_responder(200, 230020))
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert result.error == ChannelErrorKind.RATE_LIMITED
    assert len(_im_calls(fake)) == 3
    assert fake_sleep == [0.5, 1.0]


@pytest.mark.asyncio
async def test_non_retryable_business_code_fails_fast(monkeypatch, fake_sleep):
    fake = _mount(monkeypatch, _status_responder(200, 230022))
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert result.error == ChannelErrorKind.CLIENT_ERROR
    assert len(_im_calls(fake)) == 1
    assert fake_sleep == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_http_retryable_statuses(monkeypatch, fake_sleep, status):
    fake = _mount(monkeypatch, _status_responder(status))
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert len(_im_calls(fake)) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_http_non_retryable_statuses(monkeypatch, fake_sleep, status):
    fake = _mount(monkeypatch, _status_responder(status))
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert len(_im_calls(fake)) == 1


@pytest.mark.asyncio
async def test_transport_timeout_retries(monkeypatch, fake_sleep):
    class _TimeoutTransport(FakeTransport):
        def __init__(self, responder):
            super().__init__(responder)
            self.attempts = 0

        async def post_json(self, url, body, timeout, headers=None):
            if _is_token_call(url):
                return await super().post_json(url, body, timeout, headers)
            self.attempts += 1
            raise TimeoutError()

    fake = _TimeoutTransport(_ok_responder)
    feishu_client.set_transport(fake)
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert result.error == ChannelErrorKind.TIMEOUT
    assert fake.attempts == 3


@pytest.mark.asyncio
async def test_retry_then_success_no_error_log(monkeypatch, fake_sleep, caplog):
    state = {"n": 0}

    def _respond(url, body):
        if _is_token_call(url):
            return 200, _token_body()
        state["n"] += 1
        if state["n"] == 1:
            return 500, {"code": 99991400, "msg": "err"}
        return 200, SUCCESS_BODY

    _mount(monkeypatch, _respond)
    with caplog.at_level(logging.INFO, logger="app.channels.feishu.client"):
        result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is True
    client_logs = [r for r in caplog.records if r.name == "app.channels.feishu.client"]
    assert not [r for r in client_logs if r.levelno >= logging.ERROR]


@pytest.mark.asyncio
async def test_reply_idempotency_no_double_send(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    adapter = FeishuChannelAdapter()
    first = await adapter.send(_reply_message())
    second = await adapter.send(_reply_message())
    assert first.ok and second.ok
    assert len(_im_calls(fake)) == 1


@pytest.mark.asyncio
async def test_proactive_idempotency_no_double_send(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    adapter = FeishuChannelAdapter()
    await adapter.send(_proactive_message(key="k1"))
    await adapter.send(_proactive_message(key="k1"))
    assert len(_im_calls(fake)) == 1


def _use_independent_connections(monkeypatch, tmp_path):
    """把出站幂等仓储指向**独立连接**的文件库，以复现真实并发语义。

    conftest 的内存 SQLite 用 StaticPool **共享单连接**：多线程会在同一连接上交错，
    「两个进程各占一次」的竞态复现不出来（两者都会判为成功）。真实部署（PG）每个
    占位各用一条连接，故这里必须用文件库 + NullPool 才能测到唯一约束的裁决作用。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from app.core.db import Base
    from app.repositories import feishu_delivery_ledger_repository

    engine = create_engine(
        f"sqlite:///{tmp_path / 'delivery.db'}",
        poolclass=NullPool,
        connect_args={"timeout": 5},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        feishu_delivery_ledger_repository,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )


@pytest.mark.asyncio
async def test_concurrent_same_key_sends_once(monkeypatch, tmp_path):
    """幂等占位必须原子：并发调用同一键不得重复投递。

    「先查、再发（await）、后记账」的写法会在 `await` 处交错，两个调用者同时
    看到「未投递」而各发一次；本用例用会让出事件循环的 transport 固定该场景。
    """
    _use_independent_connections(monkeypatch, tmp_path)

    class _YieldingTransport(FakeTransport):
        async def post_json(self, url, body, timeout, headers=None):
            await asyncio.sleep(0)
            return await super().post_json(url, body, timeout, headers)

    fake = _YieldingTransport(_ok_responder)
    feishu_client.set_transport(fake)
    adapter = FeishuChannelAdapter()
    results = await asyncio.gather(
        adapter.send(_reply_message()),
        adapter.send(_reply_message()),
    )
    assert all(result.ok for result in results)
    assert len(_im_calls(fake)) == 1


@pytest.mark.asyncio
async def test_failed_send_releases_claim_and_allows_retry(monkeypatch, fake_sleep):
    """投递失败必须回滚占位，否则重试会被自己的幂等表永久挡住。"""
    state = {"n": 0}

    def _respond(url, body):
        if _is_token_call(url):
            return 200, _token_body()
        state["n"] += 1
        if state["n"] == 1:
            return 400, {"code": 99991400, "msg": "err"}
        return 200, SUCCESS_BODY

    _mount(monkeypatch, _respond)
    adapter = FeishuChannelAdapter()
    first = await adapter.send(_reply_message())
    second = await adapter.send(_reply_message())
    assert first.ok is False
    assert second.ok is True
    assert state["n"] == 2


@pytest.mark.asyncio
async def test_raised_send_releases_claim_and_allows_retry(monkeypatch):
    """发送**抛异常**（而非返回失败结果）时同样要回滚占位，否则重试被静默跳过。"""
    state = {"n": 0}

    class _FlakyTransport(FakeTransport):
        async def post_json(self, url, body, timeout, headers=None):
            if not _is_token_call(url):
                state["n"] += 1
                if state["n"] == 1:
                    raise RuntimeError("boom")
            return await super().post_json(url, body, timeout, headers)

    feishu_client.set_transport(_FlakyTransport(_ok_responder))
    adapter = FeishuChannelAdapter()
    first = await adapter.send(_reply_message())
    second = await adapter.send(_reply_message())
    assert first.ok is False
    assert second.ok is True
    assert state["n"] == 2


@pytest.mark.asyncio
async def test_proactive_different_keys_both_sent(monkeypatch):
    fake = _mount(monkeypatch, _ok_responder)
    adapter = FeishuChannelAdapter()
    await adapter.send(_proactive_message(key="k1"))
    await adapter.send(_proactive_message(key="k2"))
    assert len(_im_calls(fake)) == 2


# 幂等窗口（TTL 推导、过期后可重发、摊还清理）由 `test_feishu_delivery_ledger_service.py`
# 覆盖——出站幂等只有一条路径（注入的持久化实现），故不再在本文件重复。


@pytest.mark.asyncio
async def test_multi_segment_stops_after_terminal_failure(monkeypatch, fake_sleep):
    monkeypatch.setenv("FEISHU_MAX_REPLY_CHARS", "5")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        state = {"n": 0}

        def _respond(url, body):
            if _is_token_call(url):
                return 200, _token_body()
            state["n"] += 1
            if state["n"] >= 2:
                return 500, {"code": 99991400, "msg": "err"}
            return 200, SUCCESS_BODY

        fake = _mount(monkeypatch, _respond)
        long_text = "啊。" * 10
        result = await FeishuChannelAdapter().send(
            OutboundMessage(
                channel="feishu",
                recipient=RecipientRef(channel="feishu", external_id="ou_a"),
                text=long_text,
                reply_ref="om_multi",
            )
        )
        assert result.ok is False
        parts = split_text(long_text, 5)
        assert len(parts) >= 3
        assert len(_im_calls(fake)) == 1 + 3
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_disabled_produces_disabled_result(monkeypatch, override_settings):
    override_settings(feishu_enabled=False)
    fake = _mount(monkeypatch, _ok_responder)
    result = await FeishuChannelAdapter().send(_reply_message())
    assert result.ok is False
    assert result.error == ChannelErrorKind.DISABLED
    assert fake.calls == []


@pytest.mark.asyncio
async def test_send_never_raises_on_any_transport_exception(monkeypatch):
    class _ExplodingTransport:
        def __init__(self, exc):
            self._exc = exc

        async def post_json(self, url, body, timeout, headers=None):
            raise self._exc

    for exc in (RuntimeError("x"), ValueError("y"), KeyError("z"), OSError("io")):
        feishu_client.set_transport(_ExplodingTransport(exc))
        result = await FeishuChannelAdapter().send(_reply_message())
        assert isinstance(result, SendResult)
        assert result.ok is False


@pytest.mark.asyncio
async def test_token_never_leaks_into_logs(monkeypatch, caplog):
    _mount(monkeypatch, _ok_responder)
    with caplog.at_level(logging.DEBUG):
        await FeishuChannelAdapter().send(_reply_message())
    text = caplog.text
    assert "t-dlv-token" not in text
    assert "secret-dlv-value" not in text


@pytest.mark.asyncio
async def test_deliver_reply_uses_outcome_fields(monkeypatch):
    from app.channels.feishu.adapter import TurnOutcome

    captured = {}

    async def _capture_send(self, message):
        captured["message"] = message
        return SendResult(ok=True)

    monkeypatch.setattr(FeishuChannelAdapter, "send", _capture_send)
    outcome = TurnOutcome(
        session_id="feishu:ou_x",
        user_id="feishu:ou_x",
        outbound_text="回复内容",
        turn_id="t-9",
        source_message_ref="om_src_9",
        thread_ref="oc_9",
    )
    result = await deliver_reply(outcome)
    assert result.ok is True
    message = captured["message"]
    assert message.reply_ref == "om_src_9"
    assert message.text == "回复内容"
    assert message.channel == "feishu"
    assert message.metadata.get("turn_id") == "t-9"


@pytest.mark.asyncio
async def test_deliver_reply_missing_anchor_skipped(monkeypatch):
    from app.channels.feishu.adapter import TurnOutcome

    fake = _mount(monkeypatch, _ok_responder)
    outcome = TurnOutcome(
        session_id="feishu:ou_x", user_id="feishu:ou_x", outbound_text="hi",
        source_message_ref=None,
    )
    result = await deliver_reply(outcome)
    assert result.ok is False
    assert result.error == ChannelErrorKind.INVALID_REQUEST
    assert _im_calls(fake) == []


def test_delivery_module_import_face():
    import ast
    from pathlib import Path

    source = Path("app/channels/feishu/delivery.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(
                not alias.name.startswith(("app.repositories", "app.chains"))
                and "autonomy" not in alias.name
                and "life_loop" not in alias.name
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("app.repositories")
            assert not module.startswith("app.chains")
            assert "autonomy" not in module and "life_loop" not in module
