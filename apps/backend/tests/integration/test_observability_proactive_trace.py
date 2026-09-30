"""V7.8 Proactive trace：主动链路 kind=proactive/autonomy_tick 持久化。"""

import asyncio
import time
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.application.post_process import reset_user_write_locks
from app.character.asuna import PERSISTENT_GOALS
from app.core import llm_factory
from app.core.db import Message
from app.models.observability import TraceKind
from app.repositories import conversation_repository, goal_repository, trace_repository
from app.services.conversation import service as conversation_service

NOW = datetime(2026, 8, 30, 14, 0)
USER = "default-user"


def _setup(db_session_factory, session_id="s1"):
    goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(session_id, USER)
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧，我等你回来")
    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=40)
        session.commit()
    return session_id


async def _await_until(predicate, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_proactive_trace_persisted_on_delivery(db_session_factory, fake_llm, override_settings):
    override_settings(
        observability_persist_enabled=True,
        observability_prompt_capture_mode="always",
    )
    _setup(db_session_factory)
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        delivered_ids = await autonomy_engine.tick(
            user_ids=[USER], llm=llm, now=NOW + timedelta(minutes=35)
        )
        assert len(delivered_ids) == 1
        message_id = delivered_ids[0]
        assert await _await_until(
            lambda: trace_repository.get_by_turn(message_id) is not None
        )
        record = trace_repository.get_by_turn(message_id)
        assert record.kind is TraceKind.PROACTIVE
        assert record.action_id is not None
        names = {step.name for step in record.steps}
        assert {"autonomy_policy", "proactive_generate", "proactive_deliver"} <= names
        assert await _await_until(
            lambda: any(
                call.turn_id == message_id
                for call in _proactive_llm_calls()
            )
        )
    finally:
        llm_factory.reset_llm()
        reset_user_write_locks()


def _proactive_llm_calls():
    from app.repositories import llm_call_repository

    with llm_call_repository.SessionLocal() as session:
        from app.core.db import LlmCallRecordRow

        rows = session.query(LlmCallRecordRow).all()
        return [llm_call_repository._to_model(row) for row in rows]


@pytest.mark.asyncio
async def test_deny_tick_persists_autonomy_trace(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    _setup(db_session_factory)
    llm = fake_llm(response=["在吗"])
    llm_factory.set_llm(llm)
    try:
        late_night = NOW.replace(hour=23, minute=30)
        delivered_ids = await autonomy_engine.tick(
            user_ids=[USER], llm=llm, now=late_night
        )
        assert delivered_ids == []
        assert await _await_until(
            lambda: any(
                trace.kind is TraceKind.AUTONOMY_TICK
                for trace in _all_trace_rows()
            )
        )
    finally:
        llm_factory.reset_llm()


def _all_trace_rows():
    with trace_repository.SessionLocal() as session:
        from app.core.db import RuntimeTraceRow

        rows = session.query(RuntimeTraceRow).all()
        return [trace_repository._to_model(row) for row in rows]
