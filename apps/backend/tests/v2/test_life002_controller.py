"""LIFE-002 Life Loop Controller 测试。

覆盖：工作发现三来源（due trigger / inactivity eligible / goal 补扫）、
步骤管线与 skip 记账、decision 失败 abort、步骤错误不阻塞、维护步骤记账、
Idle 短路、Flag OFF 零行为、goal 到期补扫（turn 基准规则同 goal_service.review）。
"""

from datetime import datetime, timedelta

import pytest

from app.application import life_loop
from app.character.asuna import PERSISTENT_GOALS
from app.models.goal import GoalRecord
from app.repositories import (
    conversation_repository,
    goal_repository,
    loop_run_repository,
    trigger_registry_repository as trigger_repo,
)
from app.services import trigger_evaluator

NOW = datetime(2026, 9, 7, 12, 0, 0)
USER = "life-loop-user"
SESSION = "ll-s1"


@pytest.fixture()
def life_loop_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings( world_enabled="false")
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


def _setup_conversation(age_minutes=40, human_turns=1):
    goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(SESSION, USER)
    for i in range(human_turns):
        conversation_repository.save_message(SESSION, "human", f"消息 {i}")
        conversation_repository.save_message(SESSION, "ai", "好的")
    from app.core.db import Message

    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=age_minutes)
        session.commit()


class TestWorkDiscovery:
    def test_due_followup_user_discovered(self, db_session_factory, life_loop_on):
        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_evaluator.register_followup(
            USER, NOW - timedelta(minutes=1), "下午面试"
        )
        users = life_loop._collect_work_users(NOW)
        assert users == [USER]
        assert life_loop._cycle_reason(USER, NOW) == "due_trigger"

    def test_inactivity_eligible_user_discovered(
        self, db_session_factory, life_loop_on
    ):
        _setup_conversation()
        users = life_loop._collect_work_users(NOW)
        assert users == [USER]
        assert life_loop._cycle_reason(USER, NOW) == "inactivity_eligible"

    def test_fresh_conversation_not_discovered(
        self, db_session_factory, life_loop_on
    ):
        _setup_conversation(age_minutes=1)
        assert life_loop._collect_work_users(NOW) == []

    def test_fresh_reply_blocked_by_guards(self, db_session_factory, life_loop_on):
        """新鲜会话（1 分钟前）不满足闲置门槛，工作发现不收录。"""
        _setup_conversation(age_minutes=1)
        assert life_loop._collect_work_users(NOW) == []


class TestGoalCatchup:
    def test_goal_catchup_discovered_and_expired(self, db_session_factory, life_loop_on):
        _setup_conversation(age_minutes=1)
        goal_repository.create_goal(
            GoalRecord(
                user_id=USER,
                type="conversation",
                description="陪聊一次",
                horizon="current",
                created_turn=0,
                expires_at_turn=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        assert life_loop._goal_catchup_due(USER) is True
        assert life_loop._cycle_reason(USER, NOW) == "goal_catchup"
        expired = life_loop._expire_due_goals(USER)
        assert len(expired) == 1
        assert goal_repository.get_goal(expired[0].id).status == "expired"

    def test_persistent_goal_never_catchup(self, db_session_factory, life_loop_on):
        _setup_conversation()
        assert life_loop._goal_catchup_due(USER) is False


class TestUserCycle:

    @pytest.mark.asyncio
    async def test_real_decision_consumes_due_trigger(
        self, db_session_factory, life_loop_on, override_settings
    ):
        """真实 tick（静音时段覆盖 NOW → verdict=ignore，0 LLM）：decision 步骤
        经 LIFE-001 表通道领取并消费 followup trigger。"""
        conversation_repository.get_or_create_conversation(SESSION, USER)
        override_settings(
            autonomy_quiet_hours_start="11:00", autonomy_quiet_hours_end="13:00"
        )
        trigger_evaluator.register_followup(
            USER, NOW - timedelta(minutes=1), "下午面试"
        )
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["user_cycles"] == 1 and stats["aborted"] == 0
        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert run.status == "done"
        decision_step = next(s for s in run.steps if s["step"] == "decision")
        assert decision_step["status"] == "ok"
        rows = trigger_repo.list_recent(USER)
        assert len(rows) == 1 and rows[0].status == "done"

    @pytest.mark.asyncio
    async def test_decision_failure_aborts_run(
        self, db_session_factory, life_loop_on, monkeypatch
    ):
        _setup_conversation()

        async def boom(user_ids=None, llm=None, now=None):
            raise RuntimeError("decision down")

        monkeypatch.setattr(life_loop.autonomy_engine, "tick", boom)
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["aborted"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert run.status == "aborted"
        assert "perception" in [s["step"] for s in run.steps]
        decision_step = next(s for s in run.steps if s["step"] == "decision")
        assert decision_step["status"] == "error"

    @pytest.mark.asyncio
    async def test_step_error_does_not_block_following_steps(
        self, db_session_factory, life_loop_on, monkeypatch
    ):
        _setup_conversation()

        async def fake_tick(user_ids=None, llm=None, now=None):
            return []

        monkeypatch.setattr(life_loop.autonomy_engine, "tick", fake_tick)

        def divide_by_zero(*args, **kwargs):
            raise ZeroDivisionError("perception down")

        monkeypatch.setattr(life_loop.world_engine, "collect_facts", divide_by_zero)
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["user_cycles"] == 1 and stats["aborted"] == 0
        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert run.status == "done"
        perception = next(s for s in run.steps if s["step"] == "perception")
        assert perception["status"] == "error"
        assert "decision" in [s["step"] for s in run.steps]


class TestMaintenanceAndIdle:
    @pytest.mark.asyncio
    async def test_first_tick_runs_reconcile_and_records(
        self, db_session_factory, life_loop_on
    ):
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["maintenance"] == 1  # reconcile；world/action 已关
        runs = loop_run_repository.list_recent(kind="trigger_reconcile")
        assert len(runs) == 1 and runs[0].status == "done"

    @pytest.mark.asyncio
    async def test_second_tick_idle_zero_runs(self, db_session_factory, life_loop_on):
        await life_loop.run_life_loop_tick(now=NOW)
        before = len(loop_run_repository.list_recent())
        stats = await life_loop.run_life_loop_tick(now=NOW + timedelta(seconds=60))
        assert stats["idle"] is True
        assert stats["user_cycles"] == 0
        assert len(loop_run_repository.list_recent()) == before

    @pytest.mark.asyncio
    async def test_world_maintenance_dispatched_when_enabled(
        self, db_session_factory, life_loop_on, override_settings
    ):
        override_settings(world_enabled="true")
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["maintenance"] >= 2
        kinds = {r.kind for r in loop_run_repository.list_recent()}
        assert {"world_maintenance", "trigger_reconcile"} <= kinds

    @pytest.mark.asyncio
    async def test_trigger_reconcile_recovers_stale(
        self, db_session_factory, life_loop_on
    ):
        from app.core.db import TriggerRegistryRow

        key = "action_due:e-stale"
        trigger_repo.register(USER, "action_due", key, due_at=NOW, now=NOW)
        trigger_repo.register_and_claim(
            USER, "action_due", key, due_at=NOW, now=NOW
        )
        with trigger_repo.SessionLocal() as session:
            session.query(TriggerRegistryRow).filter(
                TriggerRegistryRow.trigger_key == key
            ).update({"updated_at": NOW - timedelta(seconds=900)})
            session.commit()
        stats = await life_loop.run_life_loop_tick(now=NOW)
        assert stats["maintenance"] >= 1
        row = trigger_repo.get(key)
        assert row.status == "pending"
        assert row.attempt_count == 1
