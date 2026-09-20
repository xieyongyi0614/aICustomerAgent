"""场景矩阵全链收口（FEISHU-006 §12.2）：真实管线 + 假传输 + 内存 SQLite。"""

import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.channels.base import InboundMessage
from app.channels.feishu import adapter
from app.channels.feishu import client as feishu_client
from app.channels.feishu import delivery
from app.channels.feishu.outbound import normalize_text, split_text
from app.core import llm_factory
from app.repositories import conversation_repository

TOKEN_URL_PART = "tenant_access_token"
APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_cases",
    "feishu_app_secret": "secret-cases-value",
    "feishu_verification_token": "vtoken-cases",
}

TOKEN_BODY = {"code": 0, "msg": "ok", "tenant_access_token": "t-cases-token", "expire": 7200}
SUCCESS_BODY = {"code": 0, "msg": "ok", "data": {"message_id": "om_cases_new"}}


def _structured_responses():
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
        "MemoryExtraction": {"candidates": []},
    }


def _inbound(text, open_id, reply_ref="om_cases_src"):
    return InboundMessage(
        channel="feishu",
        external_user_id=open_id,
        text=text,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reply_ref=reply_ref,
        metadata={},
    )


class CasesTransport:
    def __init__(self, responder):
        self.calls = []
        self._responder = responder

    async def post_json(self, url, body, timeout, headers=None):
        self.calls.append({"url": url, "body": dict(body)})
        status, payload = self._responder(url, body)
        return feishu_client.HttpResponse(status=status, json=payload, raw_len=64)


def _im_calls(transport):
    return [c for c in transport.calls if TOKEN_URL_PART not in c["url"]]


@pytest.fixture(autouse=True)
def _reset_state(override_settings):
    override_settings(**APP_SETTINGS)
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()
    yield
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()


@pytest.fixture(autouse=True)
def _fake_sleep():
    sleeps = []

    async def _sleep(seconds):
        sleeps.append(seconds)

    feishu_client._sleep = _sleep
    return sleeps


@pytest.mark.asyncio
async def test_case_normal_text_full_chain(db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(response=["你好呀"], structured_responses=_structured_responses())
    )
    delivered = []

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        delivered.append(json.loads(body["content"])["text"])
        return 200, SUCCESS_BODY

    transport = CasesTransport(_respond)
    feishu_client.set_transport(transport)
    outcome = await adapter.handle_inbound_message(_inbound("在吗", "ou_case_a"))
    assert outcome.error_kind is None
    assert _im_calls(transport) and delivered == ["你好呀"]
    assert conversation_repository.count_messages("feishu:ou_case_a") == 2


@pytest.mark.asyncio
async def test_case_empty_reply_fallback_sent(db_session_factory, fake_llm):
    llm_factory.set_llm(fake_llm(response="", structured_responses=_structured_responses()))
    delivered = []

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        delivered.append(json.loads(body["content"])["text"])
        return 200, SUCCESS_BODY

    transport = CasesTransport(_respond)
    feishu_client.set_transport(transport)
    outcome = await adapter.handle_inbound_message(_inbound("hi", "ou_case_b"))
    assert outcome.error_kind == "empty_response"
    assert len(_im_calls(transport)) == 1
    assert delivered == [outcome.outbound_text]
    assert outcome.outbound_text.strip()


@pytest.mark.asyncio
async def test_case_overlong_reply_segmented_losslessly(db_session_factory, fake_llm, monkeypatch):
    long_reply = "啊。" * 10
    llm_factory.set_llm(
        fake_llm(response=[long_reply], structured_responses=_structured_responses())
    )
    monkeypatch.setenv("FEISHU_MAX_REPLY_CHARS", "5")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        delivered = []

        def _respond(url, body):
            if TOKEN_URL_PART in url:
                return 200, TOKEN_BODY
            delivered.append(json.loads(body["content"])["text"])
            return 200, SUCCESS_BODY

        transport = CasesTransport(_respond)
        feishu_client.set_transport(transport)
        outcome = await adapter.handle_inbound_message(_inbound("长故事", "ou_case_c"))
        assert outcome.error_kind is None
        expected = split_text(normalize_text(outcome.outbound_text), 5)
        assert delivered == expected
        assert "".join(delivered) == normalize_text(outcome.outbound_text)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected_calls", [(429, 3), (500, 3), (400, 1), (403, 1)])
async def test_case_outbound_api_failure_matrix(
    db_session_factory, fake_llm, status, expected_calls
):
    llm_factory.set_llm(
        fake_llm(response=["回复"], structured_responses=_structured_responses())
    )

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        return status, {"code": 99991400, "msg": "err"}

    transport = CasesTransport(_respond)
    feishu_client.set_transport(transport)
    outcome = await adapter.handle_inbound_message(_inbound("hi", f"ou_case_out_{status}"))
    assert outcome.error_kind is None
    assert len(_im_calls(transport)) == expected_calls
    assert conversation_repository.count_messages(f"feishu:ou_case_out_{status}") == 2


@pytest.mark.asyncio
async def test_case_outbound_timeout_retries_then_recovers(db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(response=["第一轮"], structured_responses=_structured_responses())
    )
    state = {"fail": True}

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        if state["fail"]:
            raise TimeoutError()
        return 200, SUCCESS_BODY

    class _TimeoutTransport(CasesTransport):
        async def post_json(self, url, body, timeout, headers=None):
            self.calls.append({"url": url, "body": dict(body)})
            status, payload = self._responder(url, body)
            if status == "raise":
                raise TimeoutError()
            return feishu_client.HttpResponse(status=status, json=payload, raw_len=64)

    transport = _TimeoutTransport(_respond)
    feishu_client.set_transport(transport)
    outcome = await adapter.handle_inbound_message(
        _inbound("hi", "ou_case_timeout", reply_ref="om_case_to_1")
    )
    assert outcome.error_kind is None
    assert conversation_repository.count_messages("feishu:ou_case_timeout") == 2
    assert len(_im_calls(transport)) == 3

    state["fail"] = False
    outcome2 = await adapter.handle_inbound_message(
        _inbound("hi again", "ou_case_timeout", reply_ref="om_case_to_2")
    )
    assert outcome2.error_kind is None
    assert len(_im_calls(transport)) == 4


@pytest.mark.asyncio
async def test_case_stream_incomplete_sends_partial(db_session_factory, monkeypatch):
    calls = []

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        calls.append(content)
        yield {"kind": "token", "text": "半截"}

    monkeypatch.setattr(adapter.agent_service, "stream_chat", _stream)
    delivered = []

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        delivered.append(json.loads(body["content"])["text"])
        return 200, SUCCESS_BODY

    transport = CasesTransport(_respond)
    feishu_client.set_transport(transport)
    from datetime import datetime, timezone as tz

    inbound = InboundMessage(
        channel="feishu",
        external_user_id="ou_case_inc",
        text="hi",
        received_at=datetime(2026, 1, 1, tzinfo=tz.utc),
        reply_ref="om_inc",
        metadata={},
    )
    outcome = await adapter.handle_inbound_message(inbound)
    assert outcome.error_kind == "incomplete"
    assert outcome.outbound_text == "半截"
    assert len(_im_calls(transport)) == 1
    assert delivered == ["半截"]


@pytest.mark.asyncio
async def test_case_overload_then_recovery(db_session_factory, monkeypatch, override_settings):
    override_settings(feishu_merge_window_ms=0, feishu_session_queue_limit=1)
    release = asyncio.Event()
    started = []

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        started.append(content)
        await release.wait()
        yield {"kind": "token", "text": content}
        yield {"kind": "done", "turn_id": content}

    monkeypatch.setattr(adapter.agent_service, "stream_chat", _stream)
    delivered = []

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        delivered.append(json.loads(body["content"])["text"])
        return 200, SUCCESS_BODY

    feishu_client.set_transport(CasesTransport(_respond))

    async def _dispatch(text, open_id):
        from app.channels.base import InboundMessage as IM

        inbound = IM(
            channel="feishu",
            external_user_id=open_id,
            text=text,
            received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            reply_ref=f"om_{open_id}_{text}",
            metadata={},
        )
        await adapter.ingest_inbound_message(inbound)

    await _dispatch("m1", "ou_case_q")
    await asyncio.sleep(0.03)
    await _dispatch("m2", "ou_case_q")
    await asyncio.sleep(0.03)

    assert delivered == [adapter.FALLBACK_TEXTS["overloaded"]]
    assert started == ["m1"]

    release.set()
    await asyncio.sleep(0.05)
    await _dispatch("m3", "ou_case_q")
    await asyncio.sleep(0.05)

    assert delivered == [adapter.FALLBACK_TEXTS["overloaded"], "m1", "m3"]
    assert started == ["m1", "m3"]
    assert delivered[0] == "你发得太快了，我一条条慢慢回你～"
    assert delivered[1:] == ["m1", "m3"]
