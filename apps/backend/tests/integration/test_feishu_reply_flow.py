import asyncio
import json

import pytest

from app.channels.base import OutboundMessage, RecipientRef
from app.channels.feishu import client as feishu_client
from app.channels.feishu import delivery
from app.channels.feishu.adapter import TurnOutcome
from app.channels.feishu.delivery import deliver_reply, reset_delivery_state
from app.channels.feishu.outbound import split_text
from app.core import llm_factory
from app.repositories import conversation_repository
from datetime import datetime, timezone

from app.channels.base import InboundMessage
from app.channels.feishu import adapter

TOKEN_URL_PART = "tenant_access_token"
APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_flow",
    "feishu_app_secret": "secret-flow-value",
    "feishu_verification_token": "vtoken-flow",
}

TOKEN_BODY = {"code": 0, "msg": "ok", "tenant_access_token": "t-flow-token", "expire": 7200}
SUCCESS_BODY = {"code": 0, "msg": "ok", "data": {"message_id": "om_flow_new"}}


def _structured_responses():
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
        "MemoryExtraction": {"candidates": []},
    }


def _inbound(text, open_id, reply_ref="om_flow_src"):
    return InboundMessage(
        channel="feishu",
        external_user_id=open_id,
        text=text,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reply_ref=reply_ref,
        metadata={},
    )


class FlowTransport:
    def __init__(self, responder):
        self.calls = []
        self._responder = responder

    async def post_json(self, url, body, timeout, headers=None):
        self.calls.append({"url": url, "body": dict(body), "headers": dict(headers or {})})
        status, payload = self._responder(url, body)
        return feishu_client.HttpResponse(status=status, json=payload, raw_len=64)


def _im_calls(transport):
    return [c for c in transport.calls if TOKEN_URL_PART not in c["url"]]


@pytest.fixture(autouse=True)
def _reset_state(override_settings):
    override_settings(**APP_SETTINGS)
    reset_delivery_state()
    feishu_client.reset_feishu_client()
    yield
    reset_delivery_state()
    feishu_client.reset_feishu_client()


@pytest.mark.asyncio
async def test_full_reply_flow(db_session_factory, fake_llm, monkeypatch):
    llm_factory.set_llm(
        fake_llm(response=["你好呀"], structured_responses=_structured_responses())
    )
    im_contents = []

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        im_contents.append(json.loads(body["content"])["text"])
        return 200, SUCCESS_BODY

    transport = FlowTransport(_respond)
    feishu_client.set_transport(transport)
    outcome = await adapter.handle_inbound_message(_inbound("在吗", "ou_flow_a"))
    assert outcome.error_kind is None
    assert outcome.outbound_text == "你好呀"
    assert await _wait_until(lambda: len(_im_calls(transport)) == 1)
    reply_calls = _im_calls(transport)
    assert "/reply" in reply_calls[0]["url"]
    assert "om_flow_src" in reply_calls[0]["url"]
    assert im_contents == ["你好呀"]
    assert conversation_repository.count_messages("feishu:ou_flow_a") == 2
    assert conversation_repository.find_conversation("feishu:ou_flow_a") is not None


@pytest.mark.asyncio
async def test_delivery_failure_does_not_rollback(db_session_factory, fake_llm, monkeypatch):
    llm_factory.set_llm(
        fake_llm(response=["内容"], structured_responses=_structured_responses())
    )

    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        return 500, {"code": 99991400, "msg": "err"}

    transport = FlowTransport(_respond)
    feishu_client.set_transport(transport)
    outcome = await adapter.handle_inbound_message(_inbound("第一句", "ou_flow_b"))
    assert outcome.error_kind is None
    assert conversation_repository.count_messages("feishu:ou_flow_b") == 2

    monkeypatch.setenv("FEISHU_MAX_REPLY_CHARS", "5")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        delivered = []

        def _respond_later(url, body):
            if TOKEN_URL_PART in url:
                return 200, TOKEN_BODY
            delivered.append(json.loads(body["content"])["text"])
            return 200, SUCCESS_BODY

        transport2 = FlowTransport(_respond_later)
        feishu_client.set_transport(transport2)
        outcome2 = await adapter.handle_inbound_message(_inbound("第二句", "ou_flow_b"))
        assert outcome2.error_kind is None
        assert conversation_repository.count_messages("feishu:ou_flow_b") == 4
        assert await _wait_until(lambda: len(_im_calls(transport2)) >= 1)
        assert delivered
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_long_reply_segments_arrive_in_order(db_session_factory, fake_llm, monkeypatch):
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

        transport = FlowTransport(_respond)
        feishu_client.set_transport(transport)
        outcome = await adapter.handle_inbound_message(_inbound("讲个长故事", "ou_flow_c"))
        assert outcome.error_kind is None
        expected = split_text(outcome.outbound_text, 5)
        assert delivered == expected
        assert len(_im_calls(transport)) == len(expected)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_deliver_reply_is_sendresult_only(db_session_factory, monkeypatch):
    def _respond(url, body):
        if TOKEN_URL_PART in url:
            return 200, TOKEN_BODY
        return 200, SUCCESS_BODY

    transport = FlowTransport(_respond)
    feishu_client.set_transport(transport)
    outcome = TurnOutcome(
        session_id="feishu:ou_d",
        user_id="feishu:ou_d",
        outbound_text="  你好 ",
        source_message_ref="om_anchor",
    )
    result = await deliver_reply(outcome)
    assert result.ok is True
    reply_calls = _im_calls(transport)
    assert json.loads(reply_calls[0]["body"]["content"]) == {"text": "你好"}


async def _wait_until(predicate, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()
