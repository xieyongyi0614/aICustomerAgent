"""AUTO-005：主动消息投递链路闭合（architecture.md §21/§28，Gap G1/G2/G3）。

生成/发送两阶段：成功回填 external_message_id；Channel 失败仅重发不重生成；
发送前用户已回来 discarded；未注册 outbound 保持内部落库语义；重试耗尽终态。
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.application.chat_pipeline import active_generations
from app.application.post_process import reset_user_write_locks
from app.channels.base import ChannelErrorKind, SendResult
from app.models.autonomy import ProactiveAction
from app.repositories import conversation_repository, proactive_repository
from app.services import conversation_service
from app.services.delivery import outbound as proactive_delivery
from app.services import proactive_executor
from app.services.delivery.outbound import ProactiveOutbound
from app.services.trace_collector import TurnTraceSession

NOW = datetime(2026, 8, 30, 14, 0)
EXTERNAL_ID = "om_ext_001"


class FakeOutbound:
    def __init__(self, *results: SendResult):
        self.channel = "feishu"
        self.calls: list[tuple[str, str, str]] = []
        self._results = list(results)

    async def send(self, internal_user_id: str, text: str, idempotency_key: str):
        self.calls.append((internal_user_id, text, idempotency_key))
        return self._results.pop(0)


@pytest.fixture(autouse=True)
def _clean_state():
    reset_user_write_locks()
    autonomy_engine.reset_episode("default-user")
    yield
    active_generations.clear()
    reset_user_write_locks()
    proactive_delivery.reset_proactive_outbound()


def _action(session_id: str = "s1", **overrides) -> ProactiveAction:
    payload = {
        "id": uuid.uuid4().hex,
        "user_id": "default-user",
        "session_id": session_id,
        "trigger_type": "conversation_inactivity",
        "dedupe_key": f"inactivity:default-user:{uuid.uuid4().hex}",
        "goal_id": None,
        "intention": "check_in",
        "reason": "闲置关心",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return ProactiveAction(**payload)


def _seed_session(db_session_factory, session_id: str = "s1") -> None:
    conversation_repository.get_or_create_conversation(session_id, "default-user")
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧")


def _enqueue_and_get_active(**overrides) -> ProactiveAction:
    action = _action(**overrides)
    assert proactive_repository.enqueue(action) is True
    return proactive_repository.get_active("default-user", now=NOW)


def _outbound(outcome: FakeOutbound) -> ProactiveOutbound:
    return ProactiveOutbound(channel=outcome.channel, send=outcome.send)


@pytest.mark.asyncio
async def test_deliver_success_backfills_external_message_id(
    db_session_factory, fake_llm, monkeypatch
):
    _seed_session(db_session_factory)
    generate_calls: list[str] = []

    async def _fake_generate(*args, **kwargs):
        generate_calls.append("call")
        return "忙完了吗？记得喝口水。"

    monkeypatch.setattr(proactive_executor.proactive_chain, "generate", _fake_generate)
    outbound = FakeOutbound(SendResult(ok=True, external_message_id=EXTERNAL_ID))
    proactive_delivery.register_proactive_outbound(_outbound(outbound))

    action = _enqueue_and_get_active()
    trace = TurnTraceSession()
    delivered = await proactive_executor.execute(
        action, llm=fake_llm(), trace=trace, now=NOW
    )

    assert delivered is not None and delivered.status == "delivered"
    assert delivered.message_id is not None
    assert delivered.external_message_id == EXTERNAL_ID
    assert outbound.calls == [
        ("default-user", "忙完了吗？记得喝口水。", action.dedupe_key)
    ]
    row = proactive_repository.get_by_id(action.id)
    assert row.external_message_id == EXTERNAL_ID
    assert row.payload_text == "忙完了吗？记得喝口水。"
    step = trace.steps[-1]
    assert step.name == "proactive_deliver"
    assert step.extra["channel"] == "feishu"
    assert step.extra["external_message_id"] == EXTERNAL_ID


@pytest.mark.asyncio
async def test_send_failure_retries_resend_without_regeneration(
    db_session_factory, fake_llm, monkeypatch
):
    _seed_session(db_session_factory)
    generate_calls: list[str] = []

    async def _fake_generate(*args, **kwargs):
        generate_calls.append("call")
        return "忙完了吗？记得喝口水。"

    monkeypatch.setattr(proactive_executor.proactive_chain, "generate", _fake_generate)
    outbound = FakeOutbound(
        SendResult(ok=False, error=ChannelErrorKind.RATE_LIMITED),
        SendResult(ok=True, external_message_id=EXTERNAL_ID),
    )
    proactive_delivery.register_proactive_outbound(_outbound(outbound))

    action = _enqueue_and_get_active()
    first = await proactive_executor.execute(action, llm=fake_llm(), now=NOW)
    assert first is not None and first.status == "failed"
    assert first.attempt == 1
    assert first.next_retry_at is not None
    assert first.payload_text == "忙完了吗？记得喝口水。"
    assert first.external_message_id is None
    assert len(generate_calls) == 1

    retried_at = NOW + timedelta(minutes=5)
    active = proactive_repository.get_active("default-user", now=retried_at)
    assert active is not None and active.id == action.id
    second = await proactive_executor.execute(active, llm=fake_llm(), now=retried_at)

    assert second is not None and second.status == "delivered"
    assert second.external_message_id == EXTERNAL_ID
    assert len(generate_calls) == 1
    assert len(outbound.calls) == 2
    assert conversation_service.message_count("s1") == 3


@pytest.mark.asyncio
async def test_user_active_before_send_discards_without_sending(
    db_session_factory, fake_llm, monkeypatch
):
    _seed_session(db_session_factory)
    conversation_repository.save_message("s1", "human", "我回来了")

    async def _fail_generate(*args, **kwargs):
        raise AssertionError("发送前用户已回来，不应进入生成阶段")

    monkeypatch.setattr(proactive_executor.proactive_chain, "generate", _fail_generate)
    outbound = FakeOutbound()
    proactive_delivery.register_proactive_outbound(_outbound(outbound))

    action = _enqueue_and_get_active()
    result = await proactive_executor.execute(action, llm=fake_llm(), now=NOW)

    assert result is not None and result.status == "discarded"
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_no_outbound_registered_keeps_internal_delivery(
    db_session_factory, fake_llm, monkeypatch
):
    _seed_session(db_session_factory)
    proactive_delivery.reset_proactive_outbound()
    generate_calls: list[str] = []

    async def _fake_generate(*args, **kwargs):
        generate_calls.append("call")
        return "忙完了吗？记得喝口水。"

    monkeypatch.setattr(proactive_executor.proactive_chain, "generate", _fake_generate)

    action = _enqueue_and_get_active()
    trace = TurnTraceSession()
    delivered = await proactive_executor.execute(
        action, llm=fake_llm(), trace=trace, now=NOW
    )

    assert delivered is not None and delivered.status == "delivered"
    assert delivered.message_id is not None
    assert delivered.external_message_id is None
    assert trace.steps[-1].extra["channel"] is None


@pytest.mark.asyncio
async def test_send_retry_exhausted_terminal_failed(
    db_session_factory, fake_llm, monkeypatch
):
    _seed_session(db_session_factory)
    generate_calls: list[str] = []

    async def _fake_generate(*args, **kwargs):
        generate_calls.append("call")
        return "忙完了吗？记得喝口水。"

    monkeypatch.setattr(proactive_executor.proactive_chain, "generate", _fake_generate)
    outbound = FakeOutbound(
        SendResult(ok=False, error=ChannelErrorKind.TIMEOUT),
        SendResult(ok=False, error=ChannelErrorKind.TIMEOUT),
    )
    proactive_delivery.register_proactive_outbound(_outbound(outbound))

    action = _enqueue_and_get_active()
    first = await proactive_executor.execute(action, llm=fake_llm(), now=NOW)
    assert first is not None and first.status == "failed"
    retried_at = NOW + timedelta(minutes=5)
    active = proactive_repository.get_active("default-user", now=retried_at)
    second = await proactive_executor.execute(active, llm=fake_llm(), now=retried_at)

    assert second is not None and second.status == "failed"
    assert second.attempt == 2
    assert second.next_retry_at is None
    assert proactive_repository.get_active("default-user", now=retried_at) is None
    assert len(generate_calls) == 1
