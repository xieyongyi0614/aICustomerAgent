"""RT-016 Autonomous Loop Scheduler：AgentLoop 唯一路径 / 预算三闸 / 调度零改动（开关与回退位已删除）。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.application import agent_runtime, life_loop
from app.application.agent_runtime import controller
from app.application.agent_runtime import loop as loop_module
from app.application.agent_runtime.llm_gateway import Grant
from app.repositories import (
    conversation_repository,
    loop_run_repository,
    outbox_repository,
)
from app.services.life import budget as life_loop_budget
from app.services.autonomy import trigger as trigger_evaluator

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 7, 12, 0, 0)
USER = "rt016-user"
SESSION = "rt016-s1"

EXPECTED_STAGES = (
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
)


@pytest.fixture(autouse=True)
def _reset_budget():
    life_loop_budget.reset_cache()
    yield
    life_loop_budget.reset_cache()


@pytest.fixture()
def cycle_on(override_settings):
    trigger_evaluator._followup_registry.clear()
    override_settings()
    yield
    trigger_evaluator._followup_registry.clear()
    life_loop._maintenance_last.clear()


def _setup_conversation(age_minutes=40):
    from app.core.db import Message

    conversation_repository.get_or_create_conversation(SESSION, USER)
    conversation_repository.save_message(SESSION, "human", "在吗")
    conversation_repository.save_message(SESSION, "ai", "在的")
    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=age_minutes)
        session.commit()


def _fake_tick(monkeypatch):
    async def fake_tick(user_ids=None, llm=None, now=None):
        return []

    monkeypatch.setattr(life_loop.autonomy_engine, "tick", fake_tick)


class TestDispatchPath:
    pytestmark = pytest.mark.unit

    async def test_run_uses_agent_loop(
        self, db_session_factory, cycle_on, monkeypatch
    ):
        _setup_conversation()
        _fake_tick(monkeypatch)
        created: list = []

        class _SpyLoop(loop_module.AgentLoop):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        monkeypatch.setattr(loop_module, "AgentLoop", _SpyLoop)

        status = await controller.run_autonomous_cycle(
            USER, now=NOW, trigger_type="schedule", reason="dispatch"
        )

        assert len(created) == 1
        assert created[0].stages == EXPECTED_STAGES
        assert status in {"done", "degraded", "aborted"}
        row = loop_run_repository.list_recent(user_id=USER)[0]
        assert row.run_kind == "autonomous_tick"
        assert [s["step"] for s in row.steps if s["step"] != "abort"] == list(
            EXPECTED_STAGES
        )


class TestCycleEquivalence:
    pytestmark = pytest.mark.integration

    async def test_cleanup_and_digest_reset_equivalent(
        self, db_session_factory, cycle_on, monkeypatch
    ):
        from app.application import agent_state_assembler
        from app.core import clock as logical_clock

        unbind_calls: list = []
        reset_calls: list = []
        original_unbind = logical_clock.unbind
        original_reset = agent_state_assembler.reset_run_state

        def _unbind(token):
            unbind_calls.append(token)
            return original_unbind(token)

        def _reset(run_ctx):
            reset_calls.append(run_ctx)
            return original_reset(run_ctx)

        monkeypatch.setattr(logical_clock, "unbind", _unbind)
        monkeypatch.setattr(agent_state_assembler, "reset_run_state", _reset)

        _setup_conversation()
        _fake_tick(monkeypatch)

        await controller.run_autonomous_cycle(
            USER, now=NOW, trigger_type="schedule", reason="cleanup"
        )

        assert len(unbind_calls) == 1
        assert len(reset_calls) == 1


class TestDecisionGates:
    pytestmark = pytest.mark.integration

    async def _run_with_gates(
        self, db_session_factory, monkeypatch, override_settings, *, gate: str
    ):
        _setup_conversation()
        _fake_tick(monkeypatch)

        if gate == "quota_circuit_open":
            from app.core.db import LlmCallRecordRow

            override_settings(life_loop_daily_llm_call_budget="1")
            life_loop_budget.reset_cache()
            with db_session_factory() as session:
                session.add(
                    LlmCallRecordRow(
                        id="llm-rt016-quota",
                        call_site="proactive",
                        status="ok",
                        latency_ms=1.0,
                        input_tokens=1,
                        output_tokens=1,
                        created_at=NOW - timedelta(minutes=1),
                    )
                )
                session.commit()
            life_loop_budget.reset_cache()
        elif gate == "step_budget":
            override_settings(life_loop_cycle_llm_budget="0")
        elif gate == "gateway_denied":
            monkeypatch.setattr(
                controller,
                "acquire",
                lambda *args, **kwargs: Grant(False, False, "run_budget_exhausted"),
            )

        await controller.run_autonomous_cycle(
            USER, now=NOW, trigger_type="schedule", reason=gate
        )
        return loop_run_repository.list_recent(user_id=USER)[0]

    async def test_decision_stage_three_gates_quota_circuit_open(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        row = await self._run_with_gates(
            db_session_factory, monkeypatch, override_settings, gate="quota_circuit_open"
        )
        decision = next(s for s in row.steps if s["step"] == "decision")
        assert decision["status"] == "skipped"
        assert decision["skip_reason"] == "quota_circuit_open"

    async def test_decision_stage_three_gates_step_budget(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        row = await self._run_with_gates(
            db_session_factory, monkeypatch, override_settings, gate="step_budget"
        )
        decision = next(s for s in row.steps if s["step"] == "decision")
        assert decision["status"] == "skipped"
        assert decision["skip_reason"] == "step_budget"

    async def test_decision_stage_three_gates_gateway_denied(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        row = await self._run_with_gates(
            db_session_factory, monkeypatch, override_settings, gate="gateway_denied"
        )
        decision = next(s for s in row.steps if s["step"] == "decision")
        assert decision["status"] == "skipped"
        assert decision["skip_reason"] == "gateway_denied"


class TestSchedulerUnchanged:
    pytestmark = pytest.mark.integration

    async def test_idle_short_circuit_zero_llm_zero_runs(
        self, db_session_factory, cycle_on, monkeypatch
    ):
        _fake_tick(monkeypatch)

        await life_loop.run_life_loop_tick(now=NOW)
        before_runs = len(loop_run_repository.list_recent())
        before_calls = life_loop_budget.check_daily_budget(now=NOW).used_calls

        stats = await life_loop.run_life_loop_tick(now=NOW + timedelta(seconds=60))

        assert stats["idle"] is True
        assert stats["user_cycles"] == 0
        assert len(loop_run_repository.list_recent()) == before_runs
        assert (
            life_loop_budget.check_daily_budget(now=NOW).used_calls == before_calls
        )

    async def test_event_pregate_unchanged(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        _fake_tick(monkeypatch)
        assert await agent_runtime.run_event_pregate(now=NOW) == 0

        override_settings(AGENT_EVENT_ESCALATION_TYPES="action_result")
        _setup_conversation()
        outbox_repository.insert(
            {"user_id": USER, "world_ops": []}, "evt-rt016", now=NOW
        )
        escalated = await agent_runtime.run_event_pregate(now=NOW)
        assert escalated == 1
        run_kinds = {r.run_kind for r in loop_run_repository.list_recent(user_id=USER)}
        assert {"event_driven", "autonomous_tick"} <= run_kinds

    async def test_run_writes_loop_runs_only(
        self, db_session_factory, cycle_on, monkeypatch
    ):
        _setup_conversation()
        _fake_tick(monkeypatch)
        before = len(loop_run_repository.list_recent())

        await controller.run_autonomous_cycle(
            USER, now=NOW, trigger_type="schedule", reason="only-loop-runs"
        )

        after = loop_run_repository.list_recent()
        assert len(after) == before + 1
        assert after[0].run_kind == "autonomous_tick"


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_cycle_module_has_no_forbidden_imports(self):
        source = (
            BACKEND / "app" / "application" / "agent_runtime" / "controller.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in (
            "app.chains",
            "app.prompts",
            "app.channels.feishu",
            "app.channels",
        ):
            assert all(
                not name.startswith(forbidden) for name in imported
            ), forbidden
