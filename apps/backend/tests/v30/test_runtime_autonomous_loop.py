"""RT-016 Autonomous Loop Scheduler：开关分派 / 循环等价 / 预算三闸 / 调度零改动。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.application import agent_runtime, life_loop
from app.application.agent_runtime import controller
from app.application.agent_runtime import loop as loop_module
from app.application.agent_runtime.llm_gateway import Grant
from app.core.settings import get_settings
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


def _steps_shape(steps: list[dict]) -> list[tuple[str, ...]]:
    return [tuple(sorted(entry)) for entry in steps]


def _budget_shape(budget_state: dict) -> tuple[str, ...]:
    return tuple(sorted(budget_state))


class TestFlagDispatch:
    pytestmark = pytest.mark.unit

    def test_flag_default_is_on_after_cutover(self):
        """PLA-018 语义同步：原 `test_flag_defaults_off` 断言默认 False，
        而收敛的交付面正是「默认值与唯一有效值均为 True」。"""
        assert get_settings().runtime_autonomous_cycle_enabled is True

    async def test_flag_off_does_not_route_to_legacy(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        """PLA-018 语义同步：配置位不再改变调度路径。

        原 `test_flag_off_uses_legacy_path` 断言「开关关闭走 legacy」；收敛后该行为
        已废止（零平行路径），改为断言同一配置下**仍走 AgentLoop 且 legacy 体零调用**
        ——即「legacy 不可由配置触达」。
        """
        override_settings(runtime_autonomous_cycle_enabled="false")
        _setup_conversation()
        _fake_tick(monkeypatch)
        created: list = []
        legacy_calls: list[str] = []

        class _SpyLoop(loop_module.AgentLoop):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        monkeypatch.setattr(loop_module, "AgentLoop", _SpyLoop)
        monkeypatch.setattr(
            controller,
            "legacy_cycle_runnable",
            lambda: (lambda *a, **k: legacy_calls.append("legacy")),
        )

        status = await controller.run_autonomous_cycle(
            USER, now=NOW, trigger_type="schedule", reason="flag-off"
        )

        assert len(created) == 1
        assert created[0].stages == EXPECTED_STAGES
        assert legacy_calls == []
        assert status in {"done", "degraded", "aborted"}

    async def test_flag_on_uses_agent_loop(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        override_settings(runtime_autonomous_cycle_enabled="true")
        _setup_conversation()
        _fake_tick(monkeypatch)
        created: list = []

        class _SpyLoop(loop_module.AgentLoop):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        monkeypatch.setattr(loop_module, "AgentLoop", _SpyLoop)

        status = await controller.run_autonomous_cycle(
            USER, now=NOW, trigger_type="schedule", reason="flag-on"
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

    async def test_cycle_equivalence_with_baseline(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        """PLA-018 语义同步：对照基线改为**显式调用 legacy 执行体**。

        原用例靠 `runtime_autonomous_cycle_enabled` false/true 切换两条路径；收敛后
        该开关不再改变调度路径，故基线臂改为直接调用回退位，等价性证据得以保留。
        两次均在同一配置（false）下运行——顺带证明配置位不再影响生产入口。
        """
        from app.core.db import Message

        def _seed(user_id: str, session_id: str):
            conversation_repository.get_or_create_conversation(session_id, user_id)
            conversation_repository.save_message(session_id, "human", "在吗")
            conversation_repository.save_message(session_id, "ai", "在的")
            with conversation_repository.SessionLocal() as session:
                for row in session.query(Message).all():
                    row.created_at = NOW - timedelta(minutes=40)
                session.commit()

        _fake_tick(monkeypatch)
        user_a, session_a = "rt016-eq-a", "rt016-eq-s-a"
        user_b, session_b = "rt016-eq-b", "rt016-eq-s-b"
        _seed(user_a, session_a)
        _seed(user_b, session_b)

        override_settings(runtime_autonomous_cycle_enabled="false")
        legacy_status = await controller.legacy_cycle_runnable()(
            user_a, now=NOW, trigger_type="schedule", reason="equiv"
        )
        legacy_row = loop_run_repository.list_recent(user_id=user_a)[0]
        legacy_shape = _steps_shape(
            [s for s in legacy_row.steps if s["step"] != "abort"]
        )
        legacy_budget = _budget_shape(legacy_row.budget_state or {})

        loop_status = await controller.run_autonomous_cycle(
            user_b,
            now=NOW,
            trigger_type="schedule",
            reason="equiv",
        )
        loop_row = loop_run_repository.list_recent(user_id=user_b)[0]
        loop_shape = _steps_shape([s for s in loop_row.steps if s["step"] != "abort"])
        loop_budget = _budget_shape(loop_row.budget_state or {})

        assert legacy_status == loop_status == "done"
        assert legacy_shape == loop_shape
        assert legacy_budget == loop_budget
        assert [s["step"] for s in legacy_row.steps if s["step"] != "abort"] == [
            s["step"] for s in loop_row.steps if s["step"] != "abort"
        ]

    async def test_cleanup_and_digest_reset_equivalent(
        self, db_session_factory, cycle_on, monkeypatch, override_settings
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
        override_settings(runtime_autonomous_cycle_enabled="true")

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
        override_settings(
            runtime_autonomous_cycle_enabled="true"
        )

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
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        override_settings(runtime_autonomous_cycle_enabled="true")
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
        override_settings(runtime_autonomous_cycle_enabled="true")
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
        self, db_session_factory, cycle_on, monkeypatch, override_settings
    ):
        override_settings(runtime_autonomous_cycle_enabled="true")
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
