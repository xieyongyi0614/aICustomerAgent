"""LIFE-005 周期记忆检索与反思检查测试。

覆盖：list_top_salience 排序/门槛/hypothetical 过滤、digest 组装与预算截断、
contextvar 注入 proactive 生成上下文（前台零漂移）、反思步骤频控与 REF-003
全链委托、run.steps 记账（E-LIFE-05 trace 面）。
"""

from datetime import datetime, timedelta

import pytest

from app.application import life_loop
from app.application.life_loop_context import memory_digest_var
from app.character.asuna import PERSISTENT_GOALS
from app.core.db import Memory
from app.repositories import (
    conversation_repository,
    loop_run_repository,
    memory_repository,
    proactive_repository,
)
from app.models.goal import GoalRecord
from app.repositories import goal_repository
from app.services import life_loop_budget, trigger_evaluator

NOW = datetime(2026, 9, 7, 12, 0, 0)
USER = "life-memory-user"
SESSION = "lm-s1"


@pytest.fixture(autouse=True)
def _reset_budget_cache():
    life_loop_budget.reset_cache()
    yield
    life_loop_budget.reset_cache()


@pytest.fixture()
def life_loop_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings(
        world_enabled="false")
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()
    life_loop._reflection_check_last.clear()


def _seed_memory(memory_id, content, salience, visibility="private", memory_type="user_fact"):
    with memory_repository.SessionLocal() as session:
        session.add(
            Memory(
                id=memory_id,
                user_id=USER,
                character_id="asuna",
                type=memory_type,
                content=content,
                importance=0.8,
                confidence=0.9,
                source="user_stated",
                status="active",
                salience=salience,
                visibility=visibility,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.commit()


class TestListTopSalience:
    def test_orders_threshold_and_filters(self, db_session_factory):
        _seed_memory("m-low", "低显著度", 0.5)
        _seed_memory("m-h2", "次高", 0.85)
        _seed_memory("m-h1", "最高", 0.95)
        _seed_memory("m-hyp", "假设性的", 0.99, visibility="hypothetical")

        rows = memory_repository.list_top_salience(
            USER, min_salience=0.8, limit=5
        )
        ids = [r.id for r in rows]
        assert ids == ["m-h1", "m-h2"]
        assert "m-low" not in ids and "m-hyp" not in ids

    def test_limit_and_character_filter(self, db_session_factory):
        _seed_memory("m-a", "甲", 0.9)
        _seed_memory("m-b", "乙", 0.85)
        rows = memory_repository.list_top_salience(USER, min_salience=0.8, limit=1)
        assert [r.id for r in rows] == ["m-a"]


class TestMemoryDigestStep:
    @pytest.mark.asyncio
    async def test_step_sets_digest_and_records_ids(
        self, db_session_factory, life_loop_on
    ):
        _seed_memory("m-x", "显式嘱托", 0.95)
        cycle_ctx: dict = {}
        entry = await life_loop._step_memory_retrieval(USER, NOW, cycle_ctx)
        assert entry["status"] == "ok"
        assert entry["memory_ids"] == ["m-x"]
        assert "显式嘱托" in memory_digest_var.get()
        memory_digest_var.reset(cycle_ctx["digest_token"])
        assert memory_digest_var.get() is None

    @pytest.mark.asyncio
    async def test_digest_budget_truncated(self, db_session_factory, life_loop_on):
        _seed_memory("m-long", "长" * 300, 0.9)
        cycle_ctx: dict = {}
        await life_loop._step_memory_retrieval(USER, NOW, cycle_ctx)
        assert len(memory_digest_var.get()) <= 600
        memory_digest_var.reset(cycle_ctx["digest_token"])

    @pytest.mark.asyncio
    async def test_no_salient_memory_skips(self, db_session_factory, life_loop_on):
        cycle_ctx: dict = {}
        entry = await life_loop._step_memory_retrieval(USER, NOW, cycle_ctx)
        assert entry["status"] == "skipped"
        assert entry["skip_reason"] == "no_salient_memory"
        assert "digest_token" not in cycle_ctx


class TestProactiveDigestInjection:
    @pytest.mark.asyncio
    async def test_digest_appended_to_recent_context(
        self, db_session_factory, monkeypatch, override_settings
    ):
        from app.models.autonomy import ProactiveAction
        from app.services import proactive_executor

        override_settings()
        token = memory_digest_var.set("重要记忆摘要")
        try:
            captured: dict = {}

            async def fake_generate(
                goal_description, intention, recent_context, llm=None, trace=None
            ):
                captured["recent"] = recent_context
                return "忙完了，记得复查呀"

            monkeypatch.setattr(
                proactive_executor.proactive_chain, "generate", fake_generate
            )
            monkeypatch.setattr(
                proactive_executor, "_recent_context", lambda session_id: "最近对话"
            )
            goal = goal_repository.create_goal(
                GoalRecord(
                    user_id=USER,
                    type="user_care",
                    description="关心用户",
                    horizon="persistent",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            action = ProactiveAction(
                id="pa-digest",
                user_id=USER,
                session_id=SESSION,
                trigger_type="conversation_inactivity",
                dedupe_key="d-digest",
                goal_id=goal.id,
                intention="check_in",
                reason="闲置关心",
                created_at=NOW,
                updated_at=NOW,
            )
            assert proactive_repository.enqueue(action) is True
            delivered = await proactive_executor.execute(action, llm=None, now=NOW)
            assert delivered is not None and delivered.status == "delivered"
            assert "最近对话" in captured["recent"]
            assert "重要记忆摘要" in captured["recent"]
        finally:
            memory_digest_var.reset(token)

    @pytest.mark.asyncio
    async def test_no_digest_front_path_unchanged(
        self, db_session_factory, monkeypatch, override_settings
    ):
        from app.models.autonomy import ProactiveAction
        from app.services import proactive_executor

        assert memory_digest_var.get() is None
        captured: dict = {}

        async def fake_generate(
            goal_description, intention, recent_context, llm=None, trace=None
        ):
            captured["recent"] = recent_context
            return "在吗"

        monkeypatch.setattr(
            proactive_executor.proactive_chain, "generate", fake_generate
        )
        monkeypatch.setattr(
            proactive_executor, "_recent_context", lambda session_id: "最近对话"
        )
        goal = goal_repository.create_goal(
            GoalRecord(
                user_id=USER,
                type="user_care",
                description="关心用户",
                horizon="persistent",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        action = ProactiveAction(
            id="pa-nodigest",
            user_id=USER,
            session_id=SESSION,
            trigger_type="conversation_inactivity",
            dedupe_key="d-nodigest",
            goal_id=goal.id,
            intention="check_in",
            reason="闲置关心",
            created_at=NOW,
            updated_at=NOW,
        )
        assert proactive_repository.enqueue(action) is True
        await proactive_executor.execute(action, llm=None, now=NOW)
        assert captured["recent"] == "最近对话"


class TestReflectionCheckStep:

    def test_delegates_to_ref003_and_throttles(
        self, db_session_factory, life_loop_on, monkeypatch, override_settings
    ):
        override_settings()
        calls: list = []

        def fake_trigger(user_id, trigger="scheduled", now=None, trace=None):
            calls.append((user_id, trigger))
            return "queued"

        from app.services.reflection import triggers as reflection_triggers

        monkeypatch.setattr(
            reflection_triggers, "trigger_for_user", fake_trigger, raising=True
        )
        entry = life_loop._step_reflection_check(USER, NOW)
        assert entry["status"] == "ok" and entry["outcome"] == "queued"
        assert calls == [(USER, "event")]

        entry = life_loop._step_reflection_check(USER, NOW + timedelta(minutes=60))
        assert entry["status"] == "skipped"
        assert entry["skip_reason"] == "throttled"
        assert len(calls) == 1

        entry = life_loop._step_reflection_check(USER, NOW + timedelta(minutes=241))
        assert entry["status"] == "ok"
        assert len(calls) == 2


class TestFullCycleTrace:
    @pytest.mark.asyncio
    async def test_run_records_memory_step_trace(
        self, db_session_factory, life_loop_on, monkeypatch
    ):
        from app.core.db import Message

        goal_repository.seed_goals(USER, PERSISTENT_GOALS)
        conversation_repository.get_or_create_conversation(SESSION, USER)
        conversation_repository.save_message(SESSION, "human", "我去忙了")
        with conversation_repository.SessionLocal() as session:
            for row in session.query(Message).all():
                row.created_at = NOW - timedelta(minutes=40)
            session.commit()
        _seed_memory("m-trace", "显式嘱托复查", 0.95)

        async def fake_tick(user_ids=None, llm=None, now=None):
            return []

        monkeypatch.setattr(life_loop.autonomy_engine, "tick", fake_tick)
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["user_cycles"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        memory_step = next(s for s in run.steps if s["step"] == "memory_retrieval")
        assert memory_step["status"] == "ok"
        assert memory_step["memory_ids"] == ["m-trace"]
        assert memory_digest_var.get() is None  # 周期结束 contextvar 复位
