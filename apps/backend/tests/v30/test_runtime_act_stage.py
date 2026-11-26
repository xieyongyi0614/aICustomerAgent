"""RT-010 Action Coordination（Act 段）测试：唯一入口 / 结果必产 / 不重试 / 不决策。"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime.contracts import (
    EVENT_ACTION_COMPLETED,
    EVENT_ACTION_EXECUTED,
)
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
    RunContext,
)
from app.application.agent_runtime.session import build_session_context
from app.application.agent_runtime.stages import act as act_module
from app.application.agent_runtime.stages.act import (
    REASON_NO_ACTION,
    REASON_NO_MAPPING,
    ActOutcome,
    act,
    action_source_for,
    intent_to_action_intent,
)
from app.application.agent_runtime.stages.reason import Intention
from app.models.action import ActionResult, ActionRecord, ActionIntent
from app.services.action.executor import step_result_payload

ACT_PATH = Path(act_module.__file__)
FORBIDDEN_IMPORTS = (
    "app.chains",
    "app.prompts",
    "app.channels.feishu",
    "app.services.action.scheduler",
)
FORBIDDEN_DECISION_TOKENS = (
    "decision_pipeline",
    "autonomy_policy",
    "trigger_evaluator",
)
FORBIDDEN_SCHEDULE_TOKENS = ("next_retry_at", "scheduled_at", "retry", "enqueue_action")
FORBIDDEN_WRITE_TOKENS = ("save_record", "commit", "execute")
FORBIDDEN_WRITE_SUBSTRINGS = ("session.add", ".commit(")

NOW = datetime(2026, 9, 21, 12, 0, 0)
SESSION_ID = "S-act"
GOAL_ID = "g-act"
TOOL_ID = "builtin.reminder.create"


@pytest.fixture(autouse=True)
def _clean_bus():
    event_bus.clear_subscribers()
    yield
    event_bus.clear_subscribers()


def _intention(*, tool_id=TOOL_ID, text="continue_topic", goal_id=GOAL_ID, source="autonomy_trigger"):
    return Intention(
        intention=text,
        goal_id=goal_id,
        source=source,
        priority="P2",
        confidence=0.5,
        llm_used=False,
        degraded=False,
        audit={
            "candidates": [
                {
                    "source": "capability",
                    "intention": text,
                    "goal_id": goal_id,
                    "priority": "P2",
                    "scores": {},
                    "total": 0.5,
                    "gates": [],
                    "won": True,
                    "tool_id": tool_id,
                }
            ]
        },
        decided_at=NOW,
    )


def _run(run_kind=RUN_KIND_AUTONOMOUS_TICK, user_id="u-act"):
    return RunContext(
        run_id="r-act",
        user_id=user_id,
        run_kind=run_kind,
        trigger_type="schedule",
        reason="rt010",
        started_at=NOW,
    )


def _session(**overrides):
    return build_session_context(SESSION_ID, channel="web", now=NOW, **overrides)


def _record(*, status="succeeded", gate_reason=None, with_result=True, action_type="create_reminder"):
    record = ActionRecord(
        id="a-1",
        user_id="u-act",
        session_id=SESSION_ID,
        action_type=action_type,
        status=status,
        gate_reason=gate_reason,
        attempt=1,
        params={"content": "喝水"},
        created_at=NOW,
        updated_at=NOW,
    )
    if with_result:
        record.result = step_result_payload(
            ActionResult(
                id="res-1",
                action_id="a-1",
                status="succeeded" if status == "succeeded" else "failed",
                failure_kind=None if status == "succeeded" else "permanent",
                created_at=NOW,
            )
        )
    return record


def _stub_engine(monkeypatch, outcome):
    calls: list = []

    async def _run_action_planning(user_id, intent, session_id=None, goal_id=None, source="conversation"):
        calls.append(
            {
                "user_id": user_id,
                "intent": intent,
                "session_id": session_id,
                "goal_id": goal_id,
                "source": source,
            }
        )
        return outcome

    from app.application import action_engine

    monkeypatch.setattr(action_engine, "run_action_planning", _run_action_planning)
    return calls


_DEFAULT_SESSION = object()


def _run_act(intention, *, plan=None, run=None, trace=None, session=_DEFAULT_SESSION):
    resolved_session = _session() if session is _DEFAULT_SESSION else session
    return asyncio.run(
        act(
            intention,
            plan=plan,
            session_context=resolved_session,
            run=run or _run(),
            now=NOW,
            trace=trace,
        )
    )


class TestSingleEntry:
    pytestmark = pytest.mark.unit

    def test_act_uses_single_engine_entry(self, monkeypatch):
        calls = _stub_engine(monkeypatch, _record())

        outcome = _run_act(_intention())

        assert len(calls) == 1
        assert calls[0]["intent"].action_type == "create_reminder"
        assert calls[0]["source"] == "autonomy"
        assert isinstance(outcome, ActOutcome)
        assert outcome.action_id == "a-1"
        assert outcome.executed is True

    def test_act_module_has_no_second_orchestrator(self):
        tree = ast.parse(ACT_PATH.read_text(encoding="utf-8"))
        calls = [
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr
            in ("run_action_planning", "new_record", "assemble_plan", "evaluate_gates")
        ]

        assert calls == ["run_action_planning"]

    def test_noop_intention_returns_empty_outcome(self, monkeypatch):
        calls = _stub_engine(monkeypatch, _record())

        outcome = _run_act(_intention(text=None, tool_id=None, source="autonomy_trigger"))

        assert calls == []
        assert outcome.executed is False
        assert outcome.action_id is None
        assert outcome.result is None

    def test_noop_records_trace_reason(self, monkeypatch):
        from app.services.observability.collector import TurnTraceSession

        _stub_engine(monkeypatch, _record())
        trace = TurnTraceSession()

        _run_act(_intention(text=None, tool_id=None, source="autonomy_trigger"), trace=trace)

        assert trace.steps[-1].name == act_module.TRACE_STAGE
        assert trace.steps[-1].extra["reason"] == REASON_NO_ACTION

    def test_unmappable_candidate_returns_empty_outcome(self, monkeypatch):
        calls = _stub_engine(monkeypatch, _record())
        from app.services.observability.collector import TurnTraceSession

        trace = TurnTraceSession()
        outcome = _run_act(_intention(tool_id=None), trace=trace)

        assert calls == []
        assert outcome.executed is False
        assert trace.steps[-1].extra["reason"] == REASON_NO_MAPPING

    def test_missing_identity_is_noop(self, monkeypatch):
        calls = _stub_engine(monkeypatch, _record())

        outcome = _run_act(_intention(), run=_run(user_id=None), session=None)

        assert calls == []
        assert outcome.executed is False

    def test_intent_mapping_is_pure_mapping(self):
        mapped = intent_to_action_intent(
            _intention(), session_id=SESSION_ID, goal_id=GOAL_ID
        )

        assert isinstance(mapped, ActionIntent)
        assert mapped.action_type == "create_reminder"
        assert mapped.confidence == "ambiguous"
        assert mapped.missing_params == ["content", "due_at"]
        assert mapped.dedupe_key == f"act:create_reminder:{GOAL_ID}"

    def test_intent_mapping_confident_when_params_present(self):
        intention = _intention()
        intention.audit["candidates"][0]["params"] = {
            "content": "喝水",
            "due_at": "2026-09-21T20:00:00",
        }

        mapped = intent_to_action_intent(
            intention, session_id=SESSION_ID, goal_id=GOAL_ID
        )

        assert mapped is not None
        assert mapped.confidence == "confident"
        assert mapped.missing_params == []

    def test_action_source_for_maps_known_sources(self):
        assert action_source_for(_intention(source="chat_response")) == "conversation"
        assert action_source_for(_intention(source="autonomy_trigger")) == "autonomy"
        assert action_source_for(_intention(source="capability")) == "plan"
        assert action_source_for(_intention(source="unknown")) == "autonomy"
        assert (
            action_source_for(_intention(source="unknown"), _run(RUN_KIND_FOREGROUND_CHAT))
            == "conversation"
        )


class TestResultAlwaysProduced:
    pytestmark = pytest.mark.unit

    def test_success_yields_action_result(self, monkeypatch):
        _stub_engine(monkeypatch, _record())

        outcome = _run_act(_intention())

        assert outcome.result is not None
        assert outcome.result.status == "succeeded"
        assert outcome.failed() is False

    def test_gate_block_yields_failed_result(self, monkeypatch):
        _stub_engine(
            monkeypatch,
            _record(status="cancelled", gate_reason="ambiguous_params", with_result=False),
        )

        outcome = _run_act(_intention())

        assert outcome.result is not None
        assert outcome.result.status == "failed"
        assert outcome.result.failure_kind == "permanent"
        assert outcome.executed is False
        assert outcome.gates["gate_reason"] == "ambiguous_params"

    def test_capability_unavailable_maps_to_unavailable(self, monkeypatch):
        _stub_engine(
            monkeypatch,
            _record(
                status="cancelled",
                gate_reason="capability_unavailable",
                with_result=False,
            ),
        )

        outcome = _run_act(_intention())

        assert outcome.result is not None
        assert outcome.result.failure_kind == "unavailable"

    def test_engine_failure_yields_failed_result(self, monkeypatch):
        from app.application import action_engine

        async def _boom(*args, **kwargs):
            raise RuntimeError("engine down")

        monkeypatch.setattr(action_engine, "run_action_planning", _boom)

        outcome = _run_act(_intention())

        assert outcome.result is not None
        assert outcome.result.status == "failed"
        assert outcome.result.failure_kind == "transient"
        assert outcome.executed is False

    def test_failure_marks_degraded_not_abort(self, monkeypatch):
        _stub_engine(monkeypatch, _record(status="failed", with_result=True))
        run = _run()

        outcome = _run_act(_intention(), run=run)

        assert outcome.failed() is True
        assert run.degraded is True
        assert run.run_kind == RUN_KIND_AUTONOMOUS_TICK

    def test_success_does_not_degrade(self, monkeypatch):
        _stub_engine(monkeypatch, _record())
        run = _run()

        _run_act(_intention(), run=run)

        assert run.degraded is False


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _code_identifiers(path: Path) -> set[str]:
    """代码里出现的名字 / 属性 / 关键字实参（**不含 docstring 与字符串常量**）。

    按裸文本扫描会被 docstring 里的「零直调 `Capability.execute`」这类**声明式否定**
    误伤——本函数只取结构性使用面。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
    return found


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_act_module_has_no_forbidden_imports(self):
        imported = _imported_modules(ACT_PATH)
        offenders = [
            name
            for name in imported
            if any(
                name == prefix or name.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORTS
            )
        ]
        assert offenders == []

    def test_act_does_not_decide(self):
        used = _imported_modules(ACT_PATH) | _code_identifiers(ACT_PATH)

        assert not (used & set(FORBIDDEN_DECISION_TOKENS))

    def test_act_never_schedules_or_retries(self):
        used = _code_identifiers(ACT_PATH)

        assert not (used & set(FORBIDDEN_SCHEDULE_TOKENS))

    def test_act_performs_no_direct_writes(self):
        used = _code_identifiers(ACT_PATH)
        source = ACT_PATH.read_text(encoding="utf-8")

        assert not (used & set(FORBIDDEN_WRITE_TOKENS))
        assert not any(token in source for token in FORBIDDEN_WRITE_SUBSTRINGS)

    def test_act_outcome_is_frozen(self, monkeypatch):
        _stub_engine(monkeypatch, _record())

        outcome = _run_act(_intention())

        with pytest.raises(dataclasses.FrozenInstanceError):
            outcome.executed = True


class TestEvents:
    pytestmark = pytest.mark.unit

    def test_action_completed_event_emitted_once(self, monkeypatch, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_ACTION_COMPLETED, captured.append)
        event_bus.subscribe(EVENT_ACTION_EXECUTED, captured.append)
        override_settings(runtime_event_bus_enabled="true")
        _stub_engine(monkeypatch, _record())

        _run_act(_intention())

        completed = [e for e in captured if e.event_type == EVENT_ACTION_COMPLETED]
        executed = [e for e in captured if e.event_type == EVENT_ACTION_EXECUTED]
        assert len(completed) == 1
        assert len(executed) == 1
        assert completed[0].payload["action_id"] == "a-1"
        assert completed[0].run_id == "r-act"

    def test_events_silent_when_flag_off(self, monkeypatch, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_ACTION_COMPLETED, captured.append)
        override_settings(runtime_event_bus_enabled="false")
        _stub_engine(monkeypatch, _record())

        _run_act(_intention())

        assert captured == []

    def test_noop_emits_no_events(self, monkeypatch, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_ACTION_COMPLETED, captured.append)
        override_settings(runtime_event_bus_enabled="true")
        _stub_engine(monkeypatch, _record())

        _run_act(_intention(text=None, tool_id=None, source="autonomy_trigger"))

        assert captured == []


class TestPlanStepBranch:
    pytestmark = pytest.mark.unit

    def test_plan_step_execution_offloaded(self, monkeypatch):
        """计划步骤分支：同步仓储读取下放 `asyncio.to_thread`（打桩计数）。"""
        to_thread_calls: list = []
        real_to_thread = asyncio.to_thread

        async def _spy(func, *args, **kwargs):
            to_thread_calls.append(getattr(func, "__name__", "callable"))
            return await real_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(asyncio, "to_thread", _spy)
        executed: list = []

        async def _fake_execute(goal, plan, now, facts, settings):
            executed.append((goal, plan))
            return {"status": "ok", "step_index": 1, "outcome": "succeeded", "step_status": "done"}

        from app.application import life_loop
        from app.repositories import goal_repository

        monkeypatch.setattr(life_loop, "_execute_plan_step", _fake_execute)
        monkeypatch.setattr(
            goal_repository, "get_goal", lambda goal_id: SimpleNamespace(id=goal_id)
        )
        monkeypatch.setattr(
            goal_repository, "get_plan", lambda plan_id: SimpleNamespace(id=plan_id)
        )
        plan_value = SimpleNamespace(
            plan_id="p-1",
            goal_id=GOAL_ID,
            current_step=SimpleNamespace(index=1, tool_id=TOOL_ID),
        )

        outcome = _run_act(_intention(), plan=plan_value)

        assert to_thread_calls == ["_load"]
        assert len(executed) == 1
        assert outcome.executed is True
        assert outcome.source == "plan"
        assert outcome.result is not None
        assert outcome.result.status == "succeeded"

    def test_plan_step_failure_degrades(self, monkeypatch):
        async def _fake_execute(goal, plan, now, facts, settings):
            return {"status": "ok", "step_index": 1, "outcome": "failed", "step_status": "failed"}

        from app.application import life_loop
        from app.repositories import goal_repository

        monkeypatch.setattr(life_loop, "_execute_plan_step", _fake_execute)
        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: SimpleNamespace(id=goal_id))
        monkeypatch.setattr(goal_repository, "get_plan", lambda plan_id: SimpleNamespace(id=plan_id))
        run = _run()
        plan_value = SimpleNamespace(
            plan_id="p-1",
            goal_id=GOAL_ID,
            current_step=SimpleNamespace(index=1, tool_id=TOOL_ID),
        )

        outcome = _run_act(_intention(), plan=plan_value, run=run)

        assert outcome.result is not None
        assert outcome.result.status == "failed"
        assert run.degraded is True

    def test_plan_step_unavailable_falls_back_to_intention(self, monkeypatch):
        from app.repositories import goal_repository

        monkeypatch.setattr(goal_repository, "get_goal", lambda goal_id: None)
        monkeypatch.setattr(goal_repository, "get_plan", lambda plan_id: None)
        calls = _stub_engine(monkeypatch, _record())
        plan_value = SimpleNamespace(
            plan_id="p-1",
            goal_id=GOAL_ID,
            current_step=SimpleNamespace(index=1, tool_id=TOOL_ID),
        )

        outcome = _run_act(_intention(), plan=plan_value)

        assert len(calls) == 1
        assert outcome.action_id == "a-1"


class TestIntegration:
    pytestmark = pytest.mark.integration

    def test_act_records_legal_transition_and_single_entry(
        self, db_session_factory, monkeypatch
    ):
        from sqlalchemy import event as sqlalchemy_event
        from sqlalchemy.orm import Session

        touched: list[str] = []
        calls = _stub_engine(monkeypatch, _record())

        def _before_flush(session, flush_context, instances):
            for obj in list(session.new) + list(session.dirty) + list(session.deleted):
                touched.append(type(obj).__tablename__)

        sqlalchemy_event.listen(Session, "before_flush", _before_flush)
        try:
            outcome = _run_act(_intention())
        finally:
            sqlalchemy_event.remove(Session, "before_flush", _before_flush)

        assert len(calls) == 1
        assert outcome.result is not None
        assert outcome.result.status == "succeeded"
        assert touched == []

    def test_act_does_not_touch_action_records_when_engine_stubbed(
        self, db_session_factory, monkeypatch
    ):
        from app.core.db import Base

        def _counts():
            with db_session_factory() as session:
                return session.query(Base.metadata.tables["action_records"]).count()

        _stub_engine(monkeypatch, _record())
        before = _counts()

        _run_act(_intention())

        assert _counts() == before

    async def test_loop_act_method_delegates_to_rt010_stage(
        self, db_session_factory, monkeypatch
    ):
        from app.application import agent_runtime
        from app.application.agent_runtime.loop import AgentLoop
        from app.application.agent_runtime.profiles import get_profile

        _stub_engine(monkeypatch, _record())
        spec = get_profile(RUN_KIND_AUTONOMOUS_TICK)
        run = agent_runtime.open_run(
            "u-loop-act", RUN_KIND_AUTONOMOUS_TICK, "schedule", "rt010", NOW
        )
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry={})
        loop.intention = _intention()
        loop.session_context = _session()

        outcome = await loop.act()

        assert isinstance(outcome, ActOutcome)
        assert loop.act_outcome is outcome
        assert outcome.action_id == "a-1"
