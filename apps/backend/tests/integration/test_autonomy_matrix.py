"""V7-008：十五项必测聚合（testing.md §2）——Case 13 并发互斥 + Case 14 Scenario 全链。

Case 1~3（trigger）/4~7（policy）/8~10（action）/11（轮询）/12（重试）
分布见 test_trigger_evaluator / test_autonomy_policy / test_proactive_executor /
test_proactive_api / test_proactive_repository；本文件补并发与全链并复跑关键锚点。
"""

import asyncio
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core import timeutil
from app.application import autonomy_engine
from app.application.post_process import reset_user_write_locks
from app.character.asuna import PERSISTENT_GOALS
from app.core import llm_factory
from app.main import app
from app.repositories import (
    conversation_repository,
    goal_repository,
    proactive_repository,
)
from app.services.conversation import service as conversation_service
from app.services.autonomy import executor as proactive_executor
from app.services.observability.collector import TurnTraceSession
from tests.conftest import wait_until

NOW = timeutil.ensure_aware(datetime(2026, 8, 30, 14, 0))
USER = "default-user"


def _setup(db_session_factory, session_id="s1", content="我去忙了"):
    goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(session_id, USER)
    conversation_service.save_turn(session_id, content, "好的，去吧，我等你回来")
    from app.core.db import Message

    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=40)
        session.commit()
    return session_id


def test_case13_concurrent_executor_and_chat_turn(db_session_factory, fake_llm):
    """Executor 持锁投递期间用户消息插入：无重复、顺序合法、状态无损。"""
    _setup(db_session_factory)
    llm = fake_llm(response=["忙完了吗？"])
    action_seed = {
        "user_id": USER,
        "session_id": "s1",
        "trigger_type": "conversation_inactivity",
        "dedupe_key": "inactivity:default-user:1",
        "intention": "check_in",
        "reason": "闲置关心",
    }
    from app.models.autonomy import ProactiveAction

    action = ProactiveAction(
        id="conc-a1", created_at=NOW, updated_at=NOW, **action_seed
    )
    proactive_repository.enqueue(action)
    active = proactive_repository.get_active(USER, now=NOW)

    async def _run():
        async def _deliver():
            return await proactive_executor.execute(active, llm=llm, now=NOW)

        async def _chat_turn():
            await asyncio.sleep(0)
            conversation_service.save_turn("s1", "我回来了", "欢迎回来")
            conversation_service.reset_proactive_on_user_message(USER)

        return await asyncio.gather(_deliver(), _chat_turn())

    delivered, _ = asyncio.run(_run())
    messages = conversation_service.load_window("s1", max_messages=10)
    proactive_count = sum(1 for m in messages if m.content == "忙完了吗？")
    human_count = sum(1 for m in messages if m.role == "human")
    # 不变式（concurrency.md L3）：无重复、不覆盖、不重排——
    # 无论投递与 chat turn 以何种顺序完成，消息只追加且计数一致。
    assert proactive_count <= 1
    assert human_count == 2
    assert len(messages) == (5 if proactive_count == 1 else 4)


def test_case14_scenario_full_chain(db_session_factory, fake_llm, monkeypatch):
    """S1：我去忙了 → 闲置 → ACT(check_in) → 主动消息 → pending → ack。"""
    from app.repositories import proactive_repository

    class _SimClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW + timedelta(minutes=40)

    monkeypatch.setattr(proactive_repository, "datetime", _SimClock)
    session_id = _setup(db_session_factory)
    llm = fake_llm(response=["忙完了吗？记得喝口水。"])
    llm_factory.set_llm(llm)
    reset_user_write_locks()
    try:
        future = NOW + timedelta(minutes=35)
        delivered_ids = asyncio.run(
            autonomy_engine.tick(user_ids=[USER], llm=llm, now=future)
        )
        assert len(delivered_ids) == 1

        messages = conversation_service.load_window(session_id, max_messages=5)
        assert messages[-1].content == "忙完了吗？记得喝口水。"
        assert messages[-1].role == "ai"

        with TestClient(app) as client:
            pending = client.get("/api/v1/proactive/pending").json()["actions"]
            assert len(pending) == 1
            assert pending[0]["intention"] == "check_in"
            ack = client.post(f"/api/v1/proactive/{pending[0]['id']}/ack")
            assert ack.status_code == 200

        session = __import__(
            "app.services.observability.collector", fromlist=["get_trace_collector"]
        ).get_trace_collector().get(delivered_ids[0])
        assert session is not None
        step_names = [s.name for s in session.steps]
        assert "autonomy_policy" in step_names
        assert "proactive_deliver" in step_names
    finally:
        llm_factory.reset_llm()
        reset_user_write_locks()


def test_case14_scenario2_quiet_hours_no_action(db_session_factory, fake_llm):
    """S2：深夜闲置 → IGNORE 静音时段，零 action 行。"""
    _setup(db_session_factory)
    llm = fake_llm(response=["在吗"])
    llm_factory.set_llm(llm)
    try:
        late_night = NOW.replace(hour=23, minute=30)
        delivered_ids = asyncio.run(
            autonomy_engine.tick(user_ids=[USER], llm=llm, now=late_night)
        )
        assert delivered_ids == []
        assert proactive_repository.has_non_terminal(USER) is False
    finally:
        llm_factory.reset_llm()


def test_case14_scenario3_second_attempt_blocked(db_session_factory, fake_llm):
    """S3：第一次主动后不回应 → attempt=1 冷却中 WAIT；无第二封。"""
    _setup(db_session_factory)
    llm = fake_llm(response=["忙完了吗？"])
    llm_factory.set_llm(llm)
    try:
        future = NOW + timedelta(minutes=35)
        first = asyncio.run(autonomy_engine.tick(user_ids=[USER], llm=llm, now=future))
        assert len(first) == 1

        second = asyncio.run(
            autonomy_engine.tick(
                user_ids=[USER],
                llm=llm,
                now=future + timedelta(minutes=35),
            )
        )
        assert second == []
    finally:
        llm_factory.reset_llm()


def test_case8_depth_one_blocks_enqueue_when_active_exists(db_session_factory):
    from app.models.autonomy import ProactiveAction

    seed = {
        "user_id": USER,
        "session_id": "s1",
        "trigger_type": "conversation_inactivity",
        "intention": "check_in",
        "created_at": NOW,
        "updated_at": NOW,
    }
    first = ProactiveAction(id="d1", dedupe_key="k1", **seed)
    assert proactive_repository.enqueue(first) is True
    second = ProactiveAction(id="d2", dedupe_key="k2", **seed)
    assert proactive_repository.enqueue(second) is False
    assert wait_until(lambda: proactive_repository.has_non_terminal(USER))
