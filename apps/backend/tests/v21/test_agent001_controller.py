"""AGENT-001 Run Controller 集成测试（autonomous_tick / event_driven）。

覆盖：Flag 开启时 tick 经 Run Controller 产生 run_kind/profile 台账、
九步骤序列与 v2.0.0 等价、Gateway 第三闸接线（gateway_denied skip）、
critical 失败 abort、事件预闸白名单升级与默认零消耗。
"""

from datetime import datetime, timedelta

import pytest

from app.application import agent_runtime, life_loop
from app.application.agent_runtime.llm_gateway import Grant
from app.repositories import loop_run_repository, outbox_repository
from app.services import trigger_evaluator

NOW = datetime(2026, 9, 13, 12, 0, 0)
USER = "agent-runtime-user"
SESSION = "ar-s1"

EXPECTED_STAGES = [
    "perception",
    "state_update",
    "state_snapshot",
    "goal_check",
    "goal_stack",
    "goal_supply",
    "goal_advance",
    "memory_retrieval",
    "reflection_check",
    "decision",
    "world_experience",
]


@pytest.fixture()
def runtime_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings(
        V21_AGENT_RUNTIME_ENABLED="true",
        world_enabled="false")
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


def _register_due_followup():
    trigger_evaluator.register_followup(USER, NOW - timedelta(minutes=1), "下午面试")


def _setup_conversation(age_minutes=40):
    from app.core.db import Message
    from app.repositories import conversation_repository

    conversation_repository.get_or_create_conversation(SESSION, USER)
    conversation_repository.save_message(SESSION, "human", "在吗")
    conversation_repository.save_message(SESSION, "ai", "在的")
    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=age_minutes)
        session.commit()


def _fake_tick(monkeypatch):
    from app.application import autonomy_engine

    async def fake_tick(user_ids=None, llm=None, now=None):
        return []

    monkeypatch.setattr(autonomy_engine, "tick", fake_tick)


class TestAutonomousTickRun:
    @pytest.mark.asyncio
    async def test_tick_records_run_kind_and_profile(
        self, db_session_factory, runtime_on, monkeypatch
    ):
        from app.repositories import conversation_repository

        conversation_repository.get_or_create_conversation(SESSION, USER)
        _register_due_followup()
        _fake_tick(monkeypatch)

        stats = await life_loop.run_life_loop_tick(now=NOW)

        assert stats["user_cycles"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert run.kind == "autonomy"
        assert run.run_kind == "autonomous_tick"
        assert run.trigger_type == "schedule"
        assert run.status == "done"
        assert run.profile["budget_tier"] == "background"
        assert run.profile["critical"] == ["decision"]
        assert [s["step"] for s in run.steps] == EXPECTED_STAGES
        # A3 回归守门：台账 profile 快照必须与实际执行阶段序列一致
        assert run.profile["stages"] == [s["step"] for s in run.steps]

    @pytest.mark.asyncio
    async def test_gateway_denied_skips_decision(
        self, db_session_factory, runtime_on, monkeypatch
    ):
        from app.repositories import conversation_repository

        conversation_repository.get_or_create_conversation(SESSION, USER)
        _register_due_followup()
        _fake_tick(monkeypatch)
        monkeypatch.setattr(
            agent_runtime.controller,
            "acquire",
            lambda *args, **kwargs: Grant(False, False, "run_budget_exhausted"),
        )

        stats = await life_loop.run_life_loop_tick(now=NOW)

        assert stats["user_cycles"] == 1 and stats["aborted"] == 0
        run = loop_run_repository.list_recent(user_id=USER)[0]
        decision = next(s for s in run.steps if s["step"] == "decision")
        assert decision["status"] == "skipped"
        assert decision["skip_reason"] == "gateway_denied"

    @pytest.mark.asyncio
    async def test_decision_failure_aborts_run(
        self, db_session_factory, runtime_on, monkeypatch
    ):
        from app.application import autonomy_engine

        _setup_conversation()

        async def boom(user_ids=None, llm=None, now=None):
            raise RuntimeError("decision down")

        monkeypatch.setattr(autonomy_engine, "tick", boom)
        stats = await life_loop.run_life_loop_tick(now=NOW)

        assert stats["aborted"] == 1
        run = loop_run_repository.list_recent(user_id=USER)[0]
        assert run.status == "aborted"
        assert run.run_kind == "autonomous_tick"
        decision = next(s for s in run.steps if s["step"] == "decision")
        assert decision["status"] == "error"


class TestEventPregate:
    @pytest.mark.asyncio
    async def test_default_whitelist_zero_consumption(self, db_session_factory, runtime_on):
        outbox_repository.insert({"user_id": USER, "world_ops": []}, "evt-idle", now=NOW)
        assert await agent_runtime.run_event_pregate(now=NOW) == 0

    @pytest.mark.asyncio
    async def test_whitelisted_event_escalates(
        self, db_session_factory, runtime_on, override_settings, monkeypatch
    ):
        from app.repositories import conversation_repository

        override_settings(V21_EVENT_ESCALATION_TYPES="action_result")
        conversation_repository.get_or_create_conversation(SESSION, USER)
        outbox_repository.insert({"user_id": USER, "world_ops": []}, "evt-hit", now=NOW)
        _fake_tick(monkeypatch)

        escalated = await agent_runtime.run_event_pregate(now=NOW)

        assert escalated == 1
        run_kinds = {r.run_kind for r in loop_run_repository.list_recent(user_id=USER)}
        assert {"event_driven", "autonomous_tick"} <= run_kinds
        event_run = next(
            r
            for r in loop_run_repository.list_recent(user_id=USER)
            if r.run_kind == "event_driven"
        )
        assert event_run.trigger_type == "world_event"
        pregate = next(s for s in event_run.steps if s["step"] == "event_pregate")
        assert pregate["escalated"] is True
        cycle_run = next(
            r
            for r in loop_run_repository.list_recent(user_id=USER)
            if r.run_kind == "autonomous_tick"
        )
        assert cycle_run.trigger_type == "world_event"


class TestTriggerRouter:
    def test_background_reason_mapping(self, db_session_factory, runtime_on):
        from app.repositories import conversation_repository

        conversation_repository.get_or_create_conversation(SESSION, USER)
        trigger_type, reason = agent_runtime.classify_background_trigger(USER, NOW)
        assert reason == "inactivity_eligible"
        assert trigger_type == "threshold"

    def test_channel_message_maps_to_foreground(self):
        run_kind, trigger = agent_runtime.classify_channel_message()
        assert run_kind == "foreground_chat"
        assert trigger == "channel_message"
