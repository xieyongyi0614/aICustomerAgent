"""AUTO-006 结果记录与反思集成测试（architecture.md §25/§31）。

任一主动行为结束可回答「内部/外部消息 id、channel、是否成功、为什么产生」：
delivered/failed/discarded outcome 落 decision_records，expired 在 pending
惰性过期时回写；insight 经 memory_digest_var 注入生成上下文（学习闭环边界）。
Reflection 频控解耦已由 test_life005_cycle_retrieval 覆盖。
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app.application import observability
from app.application.life_loop_context import memory_digest_var
from app.channels.base import ChannelErrorKind, SendResult
from app.models.autonomy import ProactiveAction
from app.models.observability import DecisionKind, DecisionRecord
from app.repositories import (
    conversation_repository,
    decision_repository,
    proactive_repository,
)
from app.services import (
    conversation_service,
    proactive_delivery,
    proactive_executor,
)
from app.services.proactive_delivery import ProactiveOutbound

NOW = datetime(2026, 8, 30, 14, 0)
USER = "default-user"


class FailingOutbound:
    channel = "feishu"

    async def send(self, internal_user_id: str, text: str, idempotency_key: str):
        return SendResult(ok=False, error=ChannelErrorKind.TIMEOUT)


@pytest.fixture(autouse=True)
def _clean_state():
    from app.application.post_process import reset_user_write_locks

    reset_user_write_locks()
    yield
    reset_user_write_locks()
    proactive_delivery.reset_proactive_outbound()


def _seed_delivered(session_id="s1", delivered_at=NOW) -> ProactiveAction:
    conversation_repository.get_or_create_conversation(session_id, USER)
    action = ProactiveAction(
        id=uuid.uuid4().hex,
        user_id=USER,
        session_id=session_id,
        trigger_type="conversation_inactivity",
        dedupe_key=f"inactivity:{USER}:{uuid.uuid4().hex[:8]}",
        intention="check_in",
        reason="闲置关心",
        created_at=NOW,
        updated_at=NOW,
    )
    assert proactive_repository.enqueue(action) is True
    proactive_repository.transition(action.id, "approved", now=NOW)
    return proactive_repository.transition(
        action.id,
        "delivered",
        now=delivered_at,
        delivered_at=delivered_at,
        message_id="101",
        payload_text="忙完了吗？",
    )


def _seed_decision_record(action_id: str) -> None:
    decision_repository.save(
        DecisionRecord(
            kind=DecisionKind.PROACTIVE_AUTONOMY,
            user_id=USER,
            conversation_id="s1",
            action_id=action_id,
            trigger="conversation_inactivity",
            input_snapshot={},
            decision="act",
            reason="闲置关心",
        )
    )


def test_expired_pending_writes_decision_outcome(db_session_factory, override_settings):
    override_settings(observability_persist_enabled="true")
    action = _seed_delivered(delivered_at=NOW - timedelta(hours=25))
    _seed_decision_record(action.id)

    from app.api.v1.proactive import pending as pending_endpoint

    pending_endpoint(user_id=USER)

    records = decision_repository.search(
        user_id=USER, kind=DecisionKind.PROACTIVE_AUTONOMY, action_id=action.id
    )
    assert records[0].outcome == "expired"


@pytest.mark.asyncio
async def test_failed_send_outcome_recorded(
    db_session_factory, fake_llm, monkeypatch, override_settings
):
    override_settings(
        observability_persist_enabled="true", autonomy_max_retries=1
    )
    conversation_repository.get_or_create_conversation("s1", USER)
    conversation_service.save_turn("s1", "我去忙了", "好的，去吧")
    outcomes: list[tuple[str, str]] = []
    monkeypatch.setattr(
        observability, "mark_decision_outcome", lambda aid, o: outcomes.append((aid, o))
    )

    async def _fake_generate(*args, **kwargs):
        return "忙完了吗？"

    monkeypatch.setattr(proactive_executor.proactive_chain, "generate", _fake_generate)
    proactive_delivery.register_proactive_outbound(
        ProactiveOutbound(channel=FailingOutbound.channel, send=FailingOutbound().send)
    )
    action = ProactiveAction(
        id=uuid.uuid4().hex,
        user_id=USER,
        session_id="s1",
        trigger_type="conversation_inactivity",
        dedupe_key=f"inactivity:{USER}:{uuid.uuid4().hex[:8]}",
        intention="check_in",
        reason="闲置关心",
        created_at=NOW,
        updated_at=NOW,
    )
    assert proactive_repository.enqueue(action) is True
    active = proactive_repository.get_active(USER, now=NOW)
    await proactive_executor.execute(active, llm=fake_llm(), now=NOW)

    assert outcomes[-1][1] == "failed"


@pytest.mark.asyncio
async def test_memory_digest_injected_into_generation_context(
    db_session_factory, fake_llm, monkeypatch
):
    conversation_repository.get_or_create_conversation("s1", USER)
    conversation_service.save_turn("s1", "我去忙了", "好的，去吧")
    captured: dict[str, str] = {}

    async def _fake_generate(goal_description, intention, recent, llm=None, trace=None):
        captured["recent"] = recent
        return "忙完了吗？"

    monkeypatch.setattr(proactive_executor.proactive_chain, "generate", _fake_generate)
    action = ProactiveAction(
        id=uuid.uuid4().hex,
        user_id=USER,
        session_id="s1",
        trigger_type="conversation_inactivity",
        dedupe_key=f"inactivity:{USER}:{uuid.uuid4().hex[:8]}",
        intention="check_in",
        reason="闲置关心",
        created_at=NOW,
        updated_at=NOW,
    )
    assert proactive_repository.enqueue(action) is True
    active = proactive_repository.get_active(USER, now=NOW)
    token = memory_digest_var.set("与当前状态相关的重要记忆：\n- [event] 用户明天面试")
    try:
        await proactive_executor.execute(active, llm=fake_llm(), now=NOW)
    finally:
        memory_digest_var.reset(token)
    assert "用户明天面试" in captured["recent"]
