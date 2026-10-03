import asyncio
import time

import openai
import pytest
import httpx

from app.channels.feishu import adapter
from app.channels.feishu.adapter import FALLBACK_TEXTS
from app.core import llm_factory
from app.core.db import Conversation
from app.repositories import conversation_repository
from app.services import agent_service
from app.services.identity import channel as channel_identity_service
from app.services.observability import collector as trace_collector
from app.services.agent_service import EmptyLLMResponseError
from tests.conftest import TEST_USER_ID


def _structured_responses():
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
        "MemoryExtraction": {"candidates": []},
    }


def _inbound(text, open_id, reply_ref="om_x"):
    from datetime import datetime, timezone

    from app.channels.base import InboundMessage

    return InboundMessage(
        channel="feishu",
        external_user_id=open_id,
        text=text,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reply_ref=reply_ref,
        metadata={"tenant_key": "tk_it"},
    )


@pytest.fixture(autouse=True)
def _reset_adapter_state():
    adapter.reset_feishu_adapter()
    yield
    adapter.reset_feishu_adapter()


@pytest.mark.asyncio
async def test_full_turn_writes_exactly_two_messages(db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(response=["你好", "呀"], structured_responses=_structured_responses())
    )
    outcome = await adapter.handle_inbound_message(_inbound("在吗", "ou_full"))
    assert outcome.error_kind is None
    assert outcome.outbound_text == "你好呀"
    identity = channel_identity_service.resolve("feishu", "ou_full")
    assert outcome.user_id == identity.internal_user_id
    assert outcome.session_id == "feishu:ou_full"
    assert outcome.user_id != TEST_USER_ID
    assert conversation_repository.count_messages("feishu:ou_full") == 2
    conversation = conversation_repository.find_conversation("feishu:ou_full")
    assert conversation is not None
    assert conversation.user_id == identity.internal_user_id


@pytest.mark.asyncio
async def test_second_turn_context_contains_first(db_session_factory, fake_llm):
    llm = fake_llm(response=["好的"], structured_responses=_structured_responses())
    llm_factory.set_llm(llm)
    await adapter.handle_inbound_message(_inbound("我叫小明", "ou_multi"))
    await adapter.handle_inbound_message(_inbound("我叫什么名字", "ou_multi"))
    assert len(llm.seen_messages) >= 2
    joined_contexts = [
        " ".join(str(getattr(message, "content", message)) for message in call)
        for call in llm.seen_messages
    ]
    assert any("我叫什么名字" in context and "小明" in context for context in joined_contexts)
    with db_session_factory() as session:
        conversation_rows = (
            session.query(Conversation)
            .filter(Conversation.session_id == "feishu:ou_multi")
            .all()
        )
    assert len(conversation_rows) == 1


@pytest.mark.asyncio
async def test_same_session_serial_fifo(db_session_factory, monkeypatch):
    order = []

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        order.append(("start", content))
        await asyncio.sleep(0.05)
        order.append(("end", content))
        yield {"kind": "token", "text": content}
        yield {"kind": "done", "turn_id": content}

    monkeypatch.setattr(agent_service, "stream_chat", _stream)
    outcomes = await asyncio.gather(
        *[
            adapter.handle_inbound_message(_inbound(f"m{i}", "ou_fifo"))
            for i in range(3)
        ]
    )
    assert all(outcome.error_kind is None for outcome in outcomes)
    assert [content for kind, content in order if kind == "start"] == ["m0", "m1", "m2"]
    assert [content for kind, content in order if kind == "end"] == ["m0", "m1", "m2"]


@pytest.mark.asyncio
async def test_user_b_not_blocked_by_user_a(db_session_factory, monkeypatch):
    slow_release = asyncio.Event()
    slow_started: list[str] = []
    slow_user = channel_identity_service.resolve("feishu", "ou_slow").internal_user_id

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        if user_id == slow_user:
            slow_started.append(user_id)
            await slow_release.wait()
        yield {"kind": "token", "text": "ok"}
        yield {"kind": "done", "turn_id": "t"}

    monkeypatch.setattr(agent_service, "stream_chat", _stream)
    slow_task = asyncio.create_task(
        adapter.handle_inbound_message(_inbound("slow", "ou_slow"))
    )
    assert await _wait_turn(lambda: bool(slow_started))
    fast = await asyncio.wait_for(
        adapter.handle_inbound_message(_inbound("fast", "ou_fast")), timeout=5.0
    )
    assert fast.error_kind is None
    slow_release.set()
    slow = await slow_task
    assert slow.error_kind is None
    assert slow.user_id != fast.user_id


async def _wait_turn(predicate, timeout=5.0):
    """异步轮询等待后台 turn 推进（`conftest.wait_until` 的同步轮询会阻塞事件循环）。"""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return predicate()


@pytest.mark.asyncio
async def test_session_queue_limit_rejects_latest(db_session_factory, monkeypatch, override_settings):
    override_settings(feishu_merge_window_ms=0, feishu_session_queue_limit=1)
    started_calls = []
    release = asyncio.Event()

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        started_calls.append(content)
        await release.wait()
        yield {"kind": "token", "text": content}
        yield {"kind": "done", "turn_id": content}

    monkeypatch.setattr(agent_service, "stream_chat", _stream)
    delivered = []

    async def _record(outcome):
        delivered.append(outcome)

    monkeypatch.setattr(adapter.delivery, "deliver_reply", _record)

    await adapter.ingest_inbound_message(_inbound("m1", "ou_q"))
    assert await _wait_turn(lambda: started_calls == ["m1"])
    await adapter.ingest_inbound_message(_inbound("m2", "ou_q"))

    assert [outcome.error_kind for outcome in delivered] == ["overloaded"]
    assert delivered[0].outbound_text == FALLBACK_TEXTS["overloaded"]
    assert started_calls == ["m1"]

    release.set()
    assert await _wait_turn(lambda: len(delivered) >= 2)
    assert [outcome.outbound_text for outcome in delivered] == [
        FALLBACK_TEXTS["overloaded"],
        "m1",
    ]

    await adapter.ingest_inbound_message(_inbound("m3", "ou_q"))
    assert await _wait_turn(lambda: len(delivered) >= 3)
    assert [outcome.outbound_text for outcome in delivered] == [
        FALLBACK_TEXTS["overloaded"],
        "m1",
        "m3",
    ]
    assert started_calls == ["m1", "m3"]


@pytest.mark.asyncio
async def test_slot_released_after_pipeline_exception(db_session_factory, monkeypatch):
    async def _broken(session_id, user_id, content, llm=None, trace=None):
        raise ValueError("boom")
        yield {"kind": "token", "text": "never"}

    async def _healthy(session_id, user_id, content, llm=None, trace=None):
        yield {"kind": "token", "text": "恢复"}
        yield {"kind": "done", "turn_id": "t2"}

    monkeypatch.setattr(agent_service, "stream_chat", _broken)
    failed = await adapter.handle_inbound_message(_inbound("hi", "ou_rec"))
    assert failed.error_kind == "pipeline_error"
    monkeypatch.setattr(agent_service, "stream_chat", _healthy)
    recovered = await adapter.handle_inbound_message(_inbound("hi again", "ou_rec"))
    assert recovered.outbound_text == "恢复"
    assert adapter._session_locks == {}
    assert adapter._session_refs == {}


@pytest.mark.asyncio
async def test_identity_error_skips_pipeline(db_session_factory, monkeypatch):
    def _raise(channel, external_id, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(channel_identity_service, "resolve", _raise)
    calls = []

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        calls.append(content)
        yield {"kind": "token", "text": "x"}

    monkeypatch.setattr(agent_service, "stream_chat", _stream)
    outcome = await adapter.handle_inbound_message(_inbound("hi", "ou_ident"))
    assert outcome.error_kind == "identity_error"
    assert outcome.outbound_text == FALLBACK_TEXTS["identity_error"]
    assert calls == []


@pytest.mark.asyncio
async def test_llm_failure_writes_no_rows(db_session_factory, fake_llm):
    request = httpx.Request("POST", "https://example.invalid/v1/chat")
    response = httpx.Response(500, request=request)
    llm_factory.set_llm(
        fake_llm(
            raise_exc=openai.APIStatusError("upstream", response=response, body=None),
            structured_responses=_structured_responses(),
        )
    )
    outcome = await adapter.handle_inbound_message(_inbound("hi", "ou_llm_err"))
    assert outcome.error_kind == "llm_error"
    assert "500" not in (outcome.outbound_text or "")
    assert conversation_repository.count_messages("feishu:ou_llm_err") == 0


@pytest.mark.asyncio
async def test_empty_response_sends_fallback_not_empty_message(db_session_factory, fake_llm):
    llm_factory.set_llm(fake_llm(response="", structured_responses=_structured_responses()))
    outcome = await adapter.handle_inbound_message(_inbound("hi", "ou_empty"))
    assert outcome.error_kind == "empty_response"
    assert outcome.outbound_text == FALLBACK_TEXTS["empty_response"]


@pytest.mark.asyncio
async def test_trace_passed_through_not_duplicated(db_session_factory, monkeypatch):
    created_traces = []
    original_begin = trace_collector.get_trace_collector().begin_trace

    def _recording_begin():
        trace = original_begin()
        created_traces.append(trace)
        return trace

    monkeypatch.setattr(
        trace_collector.get_trace_collector(), "begin_trace", _recording_begin
    )
    captured = {}

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        captured["trace"] = trace
        yield {"kind": "token", "text": "x"}
        yield {"kind": "done", "turn_id": "t"}

    monkeypatch.setattr(agent_service, "stream_chat", _stream)
    await adapter.handle_inbound_message(_inbound("hi", "ou_trace"))
    assert len(created_traces) == 1
    assert captured["trace"] is created_traces[0]
