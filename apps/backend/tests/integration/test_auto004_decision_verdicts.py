"""AUTO-004 决策与候选裁决测试（architecture.md §9/§13）。

三值裁决端到端：ignore（关系浅+不宜）/wait（冷却中，保留候选下轮重评）
/act（闸门全通过 → ActionIntent 入队 Outbox）；裁决写入 decision_records
（kind=proactive_autonomy）保证可观测；硬闸门 0 LLM（纯函数，无 LLM 参与）。
"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.application.post_process import reset_user_write_locks
from app.character.asuna import PERSISTENT_GOALS
from app.models.autonomy import ProactiveAction
from app.models.observability import DecisionKind
from app.repositories import (
    conversation_repository,
    decision_repository,
    goal_repository,
    proactive_repository,
)
from app.services.conversation import service as conversation_service
from app.services.autonomy_policy import PolicySnapshot, evaluate
from app.models.autonomy import TriggerSignal

NOW = datetime(2026, 8, 30, 14, 0)
USER = "default-user"


def _setup(db_session_factory, session_id="s1"):
    goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(session_id, USER)
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧，我等你回来")
    from app.core.db import Message

    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=40)
        session.commit()
    return session_id


def test_ignore_when_shallow_relationship_and_busy():
    signal = TriggerSignal(
        type="conversation_inactivity",
        user_id=USER,
        detected_at=NOW,
        context={},
        dedupe_key="inactivity:u1:1",
    )
    snapshot = PolicySnapshot(
        intimacy=0.2,
        current_activity="工作中",
        selected_goal_type="user_care",
        last_proactive_at=None,
        attempt_count=0,
    )
    verdict = evaluate(signal, snapshot, None, NOW)
    assert verdict.decision == "ignore"
    assert "关系尚浅" in verdict.reason


def test_wait_on_cooldown_keeps_candidate_for_next_round():
    signal = TriggerSignal(
        type="conversation_inactivity",
        user_id=USER,
        detected_at=NOW,
        context={},
        dedupe_key="inactivity:u1:1",
    )
    snapshot = PolicySnapshot(
        intimacy=0.62,
        selected_goal_type="user_care",
        last_proactive_at=NOW - timedelta(minutes=10),
        attempt_count=0,
    )
    verdict = evaluate(signal, snapshot, None, NOW)
    assert verdict.decision == "wait"
    assert "冷却中" in verdict.reason


def test_act_full_chain_enqueues_outbox_and_records_decision(
    db_session_factory, fake_llm, override_settings
):
    override_settings(observability_persist_enabled="true")
    _setup(db_session_factory)
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    delivered_ids = asyncio.run(
        autonomy_engine.tick(user_ids=[USER], llm=llm, now=NOW + timedelta(minutes=35))
    )
    assert len(delivered_ids) == 1

    rows = proactive_repository.list_since(NOW)
    assert len(rows) == 1
    action = rows[0]
    assert action.type == "send_message"
    assert action.intention == "check_in"
    assert action.trigger_type == "conversation_inactivity"
    assert action.status == "delivered"

    records = decision_repository.search(user_id=USER, kind=DecisionKind.PROACTIVE_AUTONOMY)
    assert records, "act 裁决必须写入 decision_records"
    record = next(r for r in records if r.action_id == action.id)
    assert record.decision == "act"
    assert record.trigger == "conversation_inactivity"


def test_wait_decision_recorded_without_enqueue(
    db_session_factory, override_settings
):
    override_settings(observability_persist_enabled="true")
    _setup(db_session_factory)
    seed = ProactiveAction(
        id="auto004-wait-seed",
        user_id=USER,
        session_id="s1",
        trigger_type="conversation_inactivity",
        dedupe_key="inactivity:default-user:seed",
        intention="check_in",
        reason="前次投递",
        created_at=NOW,
        updated_at=NOW,
    )
    assert proactive_repository.enqueue(seed) is True
    proactive_repository.transition(seed.id, "approved", now=NOW)
    delivered_at = NOW + timedelta(minutes=30)
    proactive_repository.transition(
        seed.id, "delivered", now=delivered_at, delivered_at=delivered_at
    )

    delivered_ids = asyncio.run(
        autonomy_engine.tick(user_ids=[USER], llm=None, now=NOW + timedelta(minutes=35))
    )
    assert delivered_ids == []
    assert proactive_repository.has_non_terminal(USER) is True

    records = decision_repository.search(user_id=USER, kind=DecisionKind.PROACTIVE_AUTONOMY)
    assert records, "wait 裁决同样必须写入 decision_records"
    assert all(r.decision == "wait" for r in records)
