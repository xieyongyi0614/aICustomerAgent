"""RT-009 Planning Integration（Plan 段）测试：启用裁决 / 投影 / 降级 / 零写 / 不推进。"""

from __future__ import annotations

import ast
import dataclasses
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
)
from app.application.agent_runtime.profiles import ProfileSpec, get_profile
from app.application.agent_runtime.session import build_session_context
from app.application.agent_runtime.stages import plan as plan_module
from app.application.agent_runtime.stages.plan import (
    REASON_GOAL_MISSING,
    REASON_OPTIONAL_DISABLED,
    PlanValue,
    current_plan_value,
    plan,
    plan_enabled,
    to_plan_value,
)
from app.application.agent_runtime.stages.reason import Intention
from app.models.goal import GoalPlanRecord, GoalRecord, SubGoalSpec
from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.repositories import goal_repository
from app.services import goal_planning
from app.services.planning import context as plan_context
from app.services.planning import engine as plan_engine
from app.services.planning import scheduler as plan_scheduler

PLAN_PATH = Path(plan_module.__file__)
FORBIDDEN_IMPORTS = (
    "app.chains",
    "app.prompts",
    "app.channels.feishu",
)
FORBIDDEN_ADVANCE_TOKENS = (
    "advance_goal",
    "step_action_schedule",
    "PlanExecutorBridge",
    "execute_plan",
    "run_jobs",
    "enqueue",
    "revise(",
)
FORBIDDEN_WRITE_TOKENS = (
    "session.add",
    ".commit(",
    "create_plan",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
    "finish_goal",
)
LAZY_ONLY_MODULES = (
    "app.services.planning.engine",
    "app.services.planning.context",
    "app.services.goal_planning",
)

NOW = datetime(2026, 9, 21, 12, 0, 0)
GOAL_ID = "g-plan"


def _spec(*, optional=(), run_kind=RUN_KIND_AUTONOMOUS_TICK, budget_tier="background"):
    return ProfileSpec(
        run_kind=run_kind,
        budget_tier=budget_tier,
        stages=("perception",),
        llm_capable=frozenset(),
        critical=frozenset(),
        optional_stages=frozenset(optional),
    )


def _intention(goal_id=GOAL_ID):
    return Intention(
        intention="continue_topic",
        goal_id=goal_id,
        source="autonomy_trigger",
        priority="P2",
        confidence=0.4,
        llm_used=False,
        degraded=False,
        audit={},
        decided_at=NOW,
    )


def _goal(goal_id=GOAL_ID, user_id="u-plan", status="active", layer="short_term"):
    return GoalRecord(
        id=goal_id,
        user_id=user_id,
        type="user_care",
        description="帮用户养成早睡习惯",
        status=status,
        layer=layer,
        created_at=NOW,
        updated_at=NOW,
    )


def _plan_record(*, statuses=("pending", "pending"), status="validated", version=1):
    specs = [
        SubGoalSpec(
            index=index + 1,
            description=f"步骤{index + 1}",
            capability="create_reminder",
            criteria={"type": "action_succeeded", "capability": "create_reminder"},
            status=state,
            tool_id=None if index % 2 == 0 else "t-1",
        )
        for index, state in enumerate(statuses)
    ]
    return GoalPlanRecord(
        id="p-1",
        goal_id=GOAL_ID,
        version=version,
        status=status,
        sub_goals=specs,
        created_at=NOW,
        updated_at=NOW,
    )


def _context(goal=None):
    return PlanContext(
        goal=goal or _goal(),
        tool_surface=ToolSurface(run_kind=RUN_KIND_AUTONOMOUS_TICK),
        budget={},
    )


def _stub_assembler(monkeypatch, value, *, run_id=None):
    calls: list = []

    async def _assemble(self, goal, *, run=None, now=None):
        calls.append({"goal": goal, "run": run, "now": now})
        if run_id is not None:
            value.run = {"run_id": run_id, "run_kind": RUN_KIND_AUTONOMOUS_TICK}
        return value

    monkeypatch.setattr(plan_context.PlanContextAssembler, "assemble", _assemble)
    return calls


def _stub_engine(monkeypatch, outcome):
    calls: list = []

    class _Engine:
        async def plan(self, goal, ctx, *, trigger):
            calls.append({"goal": goal, "ctx": ctx, "trigger": trigger})
            return outcome

    monkeypatch.setattr(plan_engine, "get_planning_engine", lambda: _Engine())
    return calls


def _outcome(**overrides):
    kwargs = {"status": plan_engine.PLAN_STATUS_VALIDATED}
    kwargs.update(overrides)
    return plan_engine.PlanOutcome(**kwargs)


class TestEnablement:
    pytestmark = pytest.mark.unit

    def test_plan_enabled_requires_flag_and_profile_declaration(self, override_settings):
        declared = _spec(optional=("plan",))
        undeclared = _spec()

        override_settings(runtime_loop_optional_stages="")
        assert plan_enabled(declared) is False

        override_settings(runtime_loop_optional_stages="plan")
        assert plan_enabled(declared) is True
        assert plan_enabled(undeclared) is False

    def test_foreground_profile_never_plans(self, override_settings):
        override_settings(runtime_loop_optional_stages="plan")
        spec = get_profile(RUN_KIND_FOREGROUND_CHAT)

        assert spec.optional_stages == frozenset()
        assert plan_enabled(spec) is False

    def test_plan_stage_skipped_when_optional_disabled(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_loop_optional_stages="")
        engine_calls = _stub_engine(monkeypatch, _outcome())
        assembler_calls = _stub_assembler(monkeypatch, _context())

        value = _run_plan(_intention(), _spec(optional=("plan",)))

        assert value is None
        assert engine_calls == []
        assert assembler_calls == []

    def test_plan_stage_skipped_records_trace(self, override_settings):
        from app.services.trace_collector import TurnTraceSession

        override_settings(runtime_loop_optional_stages="")
        trace = TurnTraceSession()

        result = _run_plan(_intention(), _spec(optional=("plan",)), trace=trace)

        assert result is None
        assert trace.steps[-1].name == plan_module.TRACE_STAGE
        assert trace.steps[-1].status == "skipped"
        assert trace.steps[-1].extra["reason"] == REASON_OPTIONAL_DISABLED


class TestGuards:
    pytestmark = pytest.mark.unit

    def test_missing_goal_id_returns_none(self, monkeypatch, override_settings):
        override_settings(runtime_loop_optional_stages="plan")
        engine_calls = _stub_engine(monkeypatch, _outcome())

        value = _run_plan(_intention(goal_id=None), _spec(optional=("plan",)))

        assert value is None
        assert engine_calls == []

    def test_unknown_goal_returns_none(self, monkeypatch, override_settings):
        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: None)
        engine_calls = _stub_engine(monkeypatch, _outcome())
        from app.services.trace_collector import TurnTraceSession

        trace = TurnTraceSession()
        value = _run_plan(_intention(), _spec(optional=("plan",)), trace=trace)

        assert value is None
        assert engine_calls == []
        assert trace.steps[-1].extra["reason"] == REASON_GOAL_MISSING

    def test_context_unavailable_returns_none_without_degraded(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        _stub_assembler(monkeypatch, plan_context.PlanUnavailable("tool_system_disabled"))
        engine_calls = _stub_engine(monkeypatch, _outcome())
        run = SimpleNamespace(degraded=False)

        value = _run_plan(_intention(), _spec(optional=("plan",)), run=run)

        assert value is None
        assert engine_calls == []
        assert run.degraded is False


class TestProjection:
    pytestmark = pytest.mark.unit

    def test_plan_value_projection_matches_record(self):
        record = _plan_record(statuses=("pending", "in_progress"), version=3)

        value = to_plan_value(record, GOAL_ID)

        assert isinstance(value, PlanValue)
        assert value.plan_id == record.id
        assert value.goal_id == GOAL_ID
        assert value.status == record.status
        assert value.version == 3
        assert value.created_at == record.created_at
        assert value.budget_skipped is False
        assert value.degraded() is False
        assert [step.index for step in value.steps] == [1, 2]
        assert value.steps[0].intent == "步骤1"
        assert value.steps[0].tool_id is None
        assert value.steps[1].tool_id == "t-1"
        assert [step.status for step in value.steps] == ["pending", "in_progress"]

    def test_current_step_selection_uses_existing_semantics(self):
        record = _plan_record(statuses=("done", "pending"))
        expected = plan_scheduler.PlanScheduler.current_step(record)

        value = to_plan_value(record, GOAL_ID)

        assert expected is not None
        assert value.current_step is not None
        assert value.current_step.index == expected.index
        assert value.current_step.status == expected.status

    def test_current_step_is_none_when_all_done(self):
        record = _plan_record(statuses=("done", "done"))

        value = to_plan_value(record, GOAL_ID)

        assert plan_scheduler.PlanScheduler.current_step(record) is None
        assert value.current_step is None

    def test_current_plan_value_uses_latest_active_plan(self, monkeypatch):
        first = _plan_record(version=1)
        latest = _plan_record(version=2)
        monkeypatch.setattr(
            goal_repository,
            "list_active_plans",
            lambda user_id: [(_goal(), first), (_goal(), latest)],
        )

        value = current_plan_value("u-plan", GOAL_ID)

        assert value is not None
        assert value.version == 2

    def test_current_plan_value_returns_none_without_active_plan(self, monkeypatch):
        monkeypatch.setattr(goal_repository, "list_active_plans", lambda user_id: [])

        assert current_plan_value("u-plan", GOAL_ID) is None
        assert current_plan_value("", GOAL_ID) is None


class TestOutcome:
    pytestmark = pytest.mark.unit

    def test_plan_stage_enabled_for_background_profile(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        _stub_assembler(monkeypatch, _context())
        record = _plan_record()
        engine_calls = _stub_engine(monkeypatch, _outcome(plan=record, steps=record.sub_goals))

        value = _run_plan(_intention(), _spec(optional=("plan",)))

        assert len(engine_calls) == 1
        assert engine_calls[0]["trigger"] == goal_planning.TRIGGER_CREATED
        assert isinstance(value, PlanValue)
        assert value.plan_id == record.id

    def test_validated_outcome_records_ok_trace(self, monkeypatch, override_settings):
        from app.services.trace_collector import TurnTraceSession

        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        _stub_assembler(monkeypatch, _context())
        _stub_engine(monkeypatch, _outcome(plan=_plan_record()))
        trace = TurnTraceSession()

        _run_plan(_intention(), _spec(optional=("plan",)), trace=trace)

        assert trace.steps[-1].status == "ok"
        assert trace.steps[-1].extra["reason"] == "validated"

    def test_budget_skip_returns_none_and_marks_degraded(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        monkeypatch.setattr(goal_repository, "list_active_plans", lambda user_id: [])
        _stub_assembler(monkeypatch, _context())
        _stub_engine(
            monkeypatch,
            _outcome(
                status=plan_engine.PLAN_STATUS_SKIPPED,
                rejection_reason=plan_engine.REASON_BUDGET_DEGRADED,
            ),
        )
        run = SimpleNamespace(degraded=False)

        value = _run_plan(_intention(), _spec(optional=("plan",)), run=run)

        assert value is None
        assert run.degraded is True

    def test_budget_skip_falls_back_to_existing_plan(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        existing = _plan_record(version=4)
        monkeypatch.setattr(
            goal_repository,
            "list_active_plans",
            lambda user_id: [(_goal(), existing)],
        )
        _stub_assembler(monkeypatch, _context())
        _stub_engine(
            monkeypatch,
            _outcome(
                status=plan_engine.PLAN_STATUS_SKIPPED,
                rejection_reason=plan_engine.REASON_BUDGET_DEGRADED,
            ),
        )
        run = SimpleNamespace(degraded=False)

        value = _run_plan(_intention(), _spec(optional=("plan",)), run=run)

        assert value is not None
        assert value.budget_skipped is True
        assert value.version == 4
        assert value.degraded() is True
        assert run.degraded is True

    def test_rejected_outcome_returns_none_and_marks_degraded(
        self, monkeypatch, override_settings
    ):
        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        _stub_assembler(monkeypatch, _context())
        _stub_engine(
            monkeypatch,
            _outcome(
                status=plan_engine.PLAN_STATUS_REJECTED,
                rejection_reason=plan_engine.REASON_ATTEMPT_CAP,
            ),
        )
        run = SimpleNamespace(degraded=False)

        value = _run_plan(_intention(), _spec(optional=("plan",)), run=run)

        assert value is None
        assert run.degraded is True

    def test_engine_failure_degrades_not_raise(self, monkeypatch, override_settings):
        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        _stub_assembler(monkeypatch, _context())

        class _Boom:
            async def plan(self, goal, ctx, *, trigger):
                raise RuntimeError("engine down")

        monkeypatch.setattr(plan_engine, "get_planning_engine", lambda: _Boom())
        run = SimpleNamespace(degraded=False)

        value = _run_plan(_intention(), _spec(optional=("plan",)), run=run)

        assert value is None
        assert run.degraded is True

    def test_plan_stage_does_not_advance_steps(self, monkeypatch):
        """打桩 `PlanScheduler` 只暴露只读面：任何推进调用都会 AttributeError（D2）。"""
        real = plan_scheduler.PlanScheduler

        class _ReadOnlyScheduler:
            order = staticmethod(real.order)
            current_step = staticmethod(real.current_step)

        monkeypatch.setattr(plan_scheduler, "PlanScheduler", _ReadOnlyScheduler)

        value = to_plan_value(_plan_record(), GOAL_ID)

        assert value.current_step is not None


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_plan_module_has_no_forbidden_imports(self):
        tree = ast.parse(PLAN_PATH.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        offenders = [
            name
            for name in imported
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORTS
            )
        ]
        assert offenders == []

    def test_plan_module_performs_no_direct_writes(self):
        source = PLAN_PATH.read_text(encoding="utf-8")

        assert not any(token in source for token in FORBIDDEN_WRITE_TOKENS)

    def test_plan_module_does_not_advance_or_enqueue(self):
        source = PLAN_PATH.read_text(encoding="utf-8")

        assert not any(token in source for token in FORBIDDEN_ADVANCE_TOKENS)

    def test_planning_stack_is_imported_lazily(self):
        """规划链（引擎 / 上下文 / goal_planning）必须函数内延迟导入。

        模块级导入会拉 `app.chains` + `llm_factory` + `memory.job_worker`：实测
        `import app.services.planning.engine` 耗时约 3.1s，而本包经
        `agent_runtime/__init__` 被 `chat_pipeline` 在热路径导入。
        """
        tree = ast.parse(PLAN_PATH.read_text(encoding="utf-8"))
        module_level: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                module_level.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                module_level.add(node.module)
        assert not (module_level & set(LAZY_ONLY_MODULES))

        nested: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import):
                    nested.update(alias.name for alias in sub.names)
                elif isinstance(sub, ast.ImportFrom) and sub.module:
                    nested.add(sub.module)
        assert {"app.services", "app.services.planning"} <= nested

    def test_plan_value_is_frozen(self):
        value = to_plan_value(_plan_record(), GOAL_ID)

        with pytest.raises(dataclasses.FrozenInstanceError):
            value.status = "active"


class TestIntegration:
    pytestmark = pytest.mark.integration

    def test_plan_creates_at_most_one_plan_row(
        self, db_session_factory, monkeypatch, override_settings
    ):
        from app.core.db import Base

        override_settings(runtime_loop_optional_stages="plan")
        goal = goal_repository.create_goal(_goal())
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: goal)
        _stub_assembler(monkeypatch, _context(goal))
        monkeypatch.setattr(
            goal_planning,
            "propose_plan",
            lambda *args, **kwargs: goal_planning.PlanningProposal(
                sub_goals=[
                    {
                        "index": 1,
                        "description": "先提醒一次",
                        "capability": "create_reminder",
                        "criteria": {
                            "type": "action_succeeded",
                            "capability": "create_reminder",
                        },
                    }
                ]
            ),
        )

        def _plan_rows():
            with db_session_factory() as session:
                return session.query(Base.metadata.tables["goal_plans"]).count()

        before = _plan_rows()
        value = _run_plan(_intention(goal.id), _spec(optional=("plan",)))
        after = _plan_rows()

        assert isinstance(value, PlanValue)
        assert value.status == plan_engine.PLAN_STATUS_VALIDATED
        assert value.version == 1
        assert value.current_step is not None
        assert after - before == 1

    def test_engine_failure_creates_no_plan_row(
        self, db_session_factory, monkeypatch, override_settings
    ):
        from app.core.db import Base

        override_settings(runtime_loop_optional_stages="plan")
        goal = goal_repository.create_goal(_goal())
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: goal)
        _stub_assembler(monkeypatch, _context(goal))

        class _Boom:
            async def plan(self, goal, ctx, *, trigger):
                raise RuntimeError("engine down")

        monkeypatch.setattr(plan_engine, "get_planning_engine", lambda: _Boom())

        def _plan_rows():
            with db_session_factory() as session:
                return session.query(Base.metadata.tables["goal_plans"]).count()

        before = _plan_rows()
        value = _run_plan(_intention(goal.id), _spec(optional=("plan",)))
        after = _plan_rows()

        assert value is None
        assert after == before

    def test_plan_only_writes_goal_plan_and_run_ledger(
        self, db_session_factory, monkeypatch, override_settings
    ):
        from sqlalchemy import event as sqlalchemy_event
        from sqlalchemy.orm import Session

        override_settings(runtime_loop_optional_stages="plan")
        goal = goal_repository.create_goal(_goal())
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: goal)
        _stub_assembler(monkeypatch, _context(goal), run_id="r-plan-writes")
        monkeypatch.setattr(
            goal_planning,
            "propose_plan",
            lambda *args, **kwargs: goal_planning.PlanningProposal(
                sub_goals=[
                    {
                        "index": 1,
                        "description": "先提醒一次",
                        "capability": "create_reminder",
                        "criteria": {
                            "type": "action_succeeded",
                            "capability": "create_reminder",
                        },
                    }
                ]
            ),
        )
        touched: list[str] = []

        def _before_flush(session, flush_context, instances):
            for obj in list(session.new) + list(session.dirty) + list(session.deleted):
                touched.append(type(obj).__tablename__)

        sqlalchemy_event.listen(Session, "before_flush", _before_flush)
        try:
            _run_plan(_intention(goal.id), _spec(optional=("plan",)))
        finally:
            sqlalchemy_event.remove(Session, "before_flush", _before_flush)

        assert "goal_plans" in touched
        assert set(touched) <= {"goal_plans", "loop_runs"}

    async def test_loop_plan_method_delegates_to_rt009_stage(
        self, db_session_factory, monkeypatch, override_settings
    ):
        from app.application import agent_runtime
        from app.application.agent_runtime.loop import AgentLoop

        override_settings(runtime_loop_optional_stages="plan")
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: _goal())
        _stub_assembler(monkeypatch, _context())
        _stub_engine(monkeypatch, _outcome(plan=_plan_record()))
        spec = _spec(optional=("plan",))
        run = agent_runtime.open_run(
            "u-loop-plan", RUN_KIND_AUTONOMOUS_TICK, "schedule", "rt009", NOW
        )
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry={})
        loop.intention = _intention()

        value = await loop.plan()

        assert isinstance(value, PlanValue)
        assert loop.plan_value is value

    async def test_loop_plan_returns_none_when_disabled(self, db_session_factory):
        from app.application import agent_runtime
        from app.application.agent_runtime.loop import AgentLoop

        spec = _spec()
        run = agent_runtime.open_run(
            "u-loop-plan-off", RUN_KIND_AUTONOMOUS_TICK, "schedule", "rt009", NOW
        )
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry={})

        assert await loop.plan() is None
        assert loop.plan_value is None


def _run_plan(intention, spec, *, run=None, trace=None, session=None):
    import asyncio

    return asyncio.run(
        plan(
            intention,
            spec=spec,
            session_context=session or build_session_context("S-plan", now=NOW),
            run=run,
            now=NOW,
            trace=trace,
        )
    )
