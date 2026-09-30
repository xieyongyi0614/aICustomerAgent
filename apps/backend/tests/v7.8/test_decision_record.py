"""tests/v7.8 Decision Record Test（testing.md §2）：主动行为决策被完整记录。"""

import asyncio
import time
from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine, observability
from app.application.post_process import reset_user_write_locks
from app.character.asuna import PERSISTENT_GOALS
from app.core import llm_factory
from app.core.db import Message
from app.repositories import conversation_repository, decision_repository
from app.services.conversation import service as conversation_service

NOW = datetime(2026, 8, 30, 14, 0)
USER = "default-user"


def _setup(db_session_factory, session_id="s1", seed_goals=True):
    from app.repositories import goal_repository

    if seed_goals:
        goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(session_id, USER)
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧，我等你回来")
    return session_id


def _backdate_messages(minutes: int) -> None:
    with conversation_repository.SessionLocal() as session:
        rows = session.query(Message).all()
        for row in rows:
            row.created_at = NOW - timedelta(minutes=minutes)
        session.commit()


async def _await_until(predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_act_decision_recorded_with_outcome(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    _setup(db_session_factory)
    _backdate_messages(minutes=40)
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        delivered_ids = await autonomy_engine.tick(
            user_ids=[USER], llm=llm, now=NOW + timedelta(minutes=35)
        )
        assert len(delivered_ids) == 1
        assert await _await_until(
            lambda: any(
                record.decision == "act"
                for record in decision_repository.search(user_id=USER)
            )
        )
        act_rows = [
            record
            for record in decision_repository.search(user_id=USER)
            if record.decision == "act"
        ]
        record = act_rows[-1]
        assert record.trigger == "conversation_inactivity"
        assert record.action_id is not None
        assert record.input_snapshot.get("selected_goal_type") is not None
        assert await _await_until(
            lambda: decision_repository.get_by_action(record.action_id)[0].outcome
            == "delivered"
        )
    finally:
        llm_factory.reset_llm()
        reset_user_write_locks()


@pytest.mark.asyncio
async def test_deny_decision_recorded_on_quiet_hours(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    _setup(db_session_factory)
    _backdate_messages(minutes=40)
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
                record.decision == "ignore" and record.reason == "静音时段"
                for record in decision_repository.search(user_id=USER)
            )
        )
        deny_rows = [
            record
            for record in decision_repository.search(user_id=USER)
            if record.decision == "ignore"
        ]
        record = deny_rows[-1]
        assert record.action_id is None
        assert record.outcome is None
        assert record.input_snapshot.get("intimacy") is not None
    finally:
        llm_factory.reset_llm()


@pytest.mark.asyncio
async def test_no_trigger_no_record(db_session_factory, fake_llm, override_settings):
    override_settings(observability_persist_enabled=True)
    _setup(db_session_factory)
    _backdate_messages(minutes=10)
    llm = fake_llm(response=["好耶"])
    llm_factory.set_llm(llm)
    try:
        delivered_ids = await autonomy_engine.tick(
            user_ids=[USER], llm=llm, now=NOW + timedelta(minutes=1)
        )
        assert delivered_ids == []
        await asyncio.sleep(0.2)
        assert decision_repository.search(user_id=USER) == []
    finally:
        llm_factory.reset_llm()


@pytest.mark.asyncio
async def test_persist_disabled_records_nothing(db_session_factory, fake_llm):
    _setup(db_session_factory)
    _backdate_messages(minutes=40)
    llm = fake_llm(response=["忙完了吗？"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        delivered_ids = await autonomy_engine.tick(
            user_ids=[USER], llm=llm, now=NOW + timedelta(minutes=35)
        )
        assert len(delivered_ids) == 1
        await asyncio.sleep(0.3)
        assert decision_repository.search(user_id=USER) == []
        assert observability.background_tasks == set()
    finally:
        llm_factory.reset_llm()
        reset_user_write_locks()
