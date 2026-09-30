"""RT-008 Reasoning Layer（Reason 段）测试：单入口 / 分叉 / 预算 / 降级 / 零写。"""

from __future__ import annotations

import ast
import dataclasses
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application import autonomy_engine, world_engine
from app.application.agent_runtime import events as event_bus
from app.application.agent_runtime import state as state_manager
from app.application.agent_runtime.contracts import (
    EVENT_DECISION_MADE,
    RuntimeInput,
)
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
    RunContext,
)
from app.application.agent_runtime.profiles import get_profile
from app.application.agent_runtime.session import build_session_context
from app.application.agent_runtime.stages import reason as reason_module
from app.application.agent_runtime.stages.reason import (
    FACT_SET_GOAL_STACK,
    FACT_SET_SNAPSHOT,
    FACT_SET_TOOL_INSIGHTS,
    FACT_SET_WORLD,
    Intention,
    build_stack,
    capabilities_for,
    reason,
)
from app.models.agent_state import AgentStateSnapshot
from app.engines import decision as decision_pipeline
from app.services.goal import stack as goal_stack_service

REASON_PATH = Path(reason_module.__file__)
FORBIDDEN_IMPORTS = (
    "app.repositories",
    "app.chains",
    "app.prompts",
    "app.channels.feishu",
    "app.application.chat_pipeline",
)
FORBIDDEN_WRITE_TOKENS = ("session.add", ".commit(", "INSERT ", "UPDATE ", "DELETE ")
FORBIDDEN_MATH_TOKENS = (
    "def collect_candidates",
    "def score_candidates",
    "def run_risk_gates",
    "def select",
    "def assign_priorities",
    "def _intention_for",
)

SESSION_ID = "S-reason"
DECIDED_AT = datetime(2026, 9, 21, 12, 0, 0)
NOW = DECIDED_AT


@pytest.fixture(autouse=True)
def _clean_bus():
    event_bus.clear_subscribers()
    yield
    event_bus.clear_subscribers()


def _session(**overrides):
    return build_session_context(
        SESSION_ID,
        channel="web",
        external_user_id="u-ext",
        run_id="r-reason",
        now=DECIDED_AT,
        **overrides,
    )


def _run(run_kind=RUN_KIND_FOREGROUND_CHAT, user_id=SESSION_ID):
    return RunContext(
        run_id="r-reason",
        user_id=user_id,
        run_kind=run_kind,
        trigger_type="channel_message",
        reason="rt008",
        started_at=DECIDED_AT,
    )


def _observation(kind="channel_message"):
    return SimpleNamespace(kind=kind, dedupe_key=f"{kind}:web:0" * 1)


def _stub_pipeline(monkeypatch, **overrides):
    """打桩 `run_pipeline`，返回 (调用记录, 默认结果)。"""
    calls: list[dict] = []
    winner = overrides.pop(
        "winner", decision_pipeline.Candidate("chat_response", "continue_topic", None)
    )
    winner.won = True
    audit = overrides.pop(
        "audit",
        {
            "candidates": [
                {
                    "source": winner.source,
                    "intention": winner.intention,
                    "goal_id": None,
                    "priority": "P0",
                    "scores": {},
                    "total": 0.7,
                    "gates": [{"budget_cooldown": "pass", "reason": "ok"}],
                    "won": True,
                }
            ]
        },
    )
    result = decision_pipeline.DecisionResult(
        winner=winner, intention="continue_topic", audit=audit
    )

    def _run_pipeline(**kwargs):
        calls.append(kwargs)
        return result

    monkeypatch.setattr(decision_pipeline, "run_pipeline", _run_pipeline)
    return calls, result


def _silence_audit(reason_text: str = "quota_circuit_open") -> dict:
    return {
        "candidates": [
            {
                "source": "autonomy_trigger",
                "intention": "continue_topic",
                "goal_id": None,
                "priority": "P2",
                "scores": {},
                "total": 0.4,
                "gates": [{"budget_cooldown": "rejected", "reason": reason_text}],
                "won": False,
            },
            {
                "source": "silence",
                "intention": None,
                "goal_id": None,
                "priority": "P4",
                "scores": {},
                "total": 0.0,
                "gates": [{"budget_cooldown": "pass", "reason": "zero_cost"}],
                "won": True,
            },
        ]
    }


class TestSinglePipelineEntry:
    pytestmark = pytest.mark.unit

    async def test_reason_uses_single_pipeline_entry(self, monkeypatch):
        calls, _ = _stub_pipeline(monkeypatch)

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert len(calls) == 1

    async def test_reason_module_has_no_second_decision_implementation(self):
        source = REASON_PATH.read_text(encoding="utf-8")

        assert not any(token in source for token in FORBIDDEN_MATH_TOKENS)

    async def test_intention_wraps_winner_fields(self, monkeypatch):
        winner = decision_pipeline.Candidate("capability", None, "g-1", {"tool_id": "t1"})
        _stub_pipeline(
            monkeypatch,
            winner=winner,
            audit={
                "candidates": [
                    {
                        "source": "capability",
                        "intention": None,
                        "goal_id": "g-1",
                        "priority": "P1",
                        "scores": {"interest": 1.0},
                        "total": 0.83,
                        "gates": [{"budget_cooldown": "pass", "reason": "ok"}],
                        "won": True,
                    }
                ]
            },
        )

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_AUTONOMOUS_TICK),
            run=_run(RUN_KIND_AUTONOMOUS_TICK),
            now=NOW,
        )

        assert isinstance(intention, Intention)
        assert intention.source == "capability"
        assert intention.goal_id == "g-1"
        assert intention.confidence == winner.total
        assert intention.priority == decision_pipeline.PRIORITY_LABELS[winner.priority]
        assert intention.decided_at == NOW
        assert intention.audit["candidates"][0]["source"] == "capability"
        assert intention.llm_used is True
        assert intention.degraded is False

    async def test_silence_winner_has_no_llm(self, monkeypatch):
        winner = decision_pipeline.Candidate("silence", None, None)
        _stub_pipeline(
            monkeypatch,
            winner=winner,
            audit={
                "candidates": [
                    {
                        "source": "silence",
                        "intention": None,
                        "goal_id": None,
                        "priority": "P4",
                        "scores": {},
                        "total": 0.0,
                        "gates": [{"budget_cooldown": "pass", "reason": "zero_cost"}],
                        "won": True,
                    }
                ]
            },
        )

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert intention.source == "silence"
        assert intention.llm_used is False
        assert intention.degraded is False


class TestFrontBackFork:
    pytestmark = pytest.mark.unit

    async def test_front_and_back_inputs_differ_only_by_chat_flags(self, monkeypatch):
        calls, _ = _stub_pipeline(monkeypatch)

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            chat_response_intention="continue_topic",
            trigger_intention="share_own_feeling",
            trigger_goal_id="g-trigger",
            run=_run(),
            now=NOW,
        )
        front = calls[-1]
        assert front["chat_response"] is True
        assert front["chat_response_intention"] == "continue_topic"
        assert front["trigger_intention"] is None
        assert front["trigger_goal_id"] is None
        assert front["capabilities"] is None

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_AUTONOMOUS_TICK),
            chat_response_intention="continue_topic",
            trigger_intention="share_own_feeling",
            trigger_goal_id="g-trigger",
            run=_run(RUN_KIND_AUTONOMOUS_TICK),
            now=NOW,
        )
        back = calls[-1]
        assert back["chat_response"] is False
        assert back["chat_response_intention"] is None
        assert back["trigger_intention"] == "share_own_feeling"
        assert back["trigger_goal_id"] == "g-trigger"

    def test_capabilities_only_for_autonomous_profile(self, monkeypatch):
        monkeypatch.setattr(
            autonomy_engine,
            "resolve_autonomy_surface",
            lambda user_id, now=None: SimpleNamespace(tool_ids=("t1", "t2")),
        )

        assert capabilities_for(get_profile(RUN_KIND_FOREGROUND_CHAT)) is None
        assert capabilities_for(get_profile(RUN_KIND_AUTONOMOUS_TICK), user_id="u") == [
            "t1",
            "t2",
        ]

    def test_capabilities_degrade_to_none_on_failure(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("registry down")

        monkeypatch.setattr(autonomy_engine, "resolve_autonomy_surface", _boom)

        assert capabilities_for(get_profile(RUN_KIND_AUTONOMOUS_TICK), user_id="u") is None

    async def test_pipeline_receives_run_and_world_inputs(self, monkeypatch):
        calls, _ = _stub_pipeline(monkeypatch)
        monkeypatch.setattr(
            world_engine,
            "collect_facts",
            lambda user_id, provider=None: {
                "impacts": [{"kind": "weather"}],
                "current_block": "morning",
                "part_of_day": "上午",
            },
        )
        monkeypatch.setattr(
            autonomy_engine,
            "collect_tool_insights",
            lambda user_id: {"count": 1, "insights": [{"note": "n1"}]},
        )
        run = _run()

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=run,
            now=NOW,
        )

        sent = calls[-1]
        assert sent["run"] is run
        assert sent["world_impacts"] == [{"kind": "weather"}]
        assert sent["world_schedule"] == {
            "current_block": "morning",
            "part_of_day": "上午",
        }
        assert sent["tool_insights"] == [{"note": "n1"}]
        assert sent["now"] == NOW

    async def test_frozen_state_preferred_over_snapshot(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise AssertionError("传入冻结态时不得再取快照")

        monkeypatch.setattr(state_manager, "snapshot", _boom)
        calls, _ = _stub_pipeline(monkeypatch)
        frozen = SimpleNamespace(
            snapshot=AgentStateSnapshot(snapshot_version=9), snapshot_version=9
        )

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            runtime_state=frozen,
            run=_run(),
            now=NOW,
        )

        assert calls[-1]["snapshot"].snapshot_version == 9


class TestBudgetFallback:
    pytestmark = pytest.mark.unit

    async def test_gateway_denied_falls_back_without_llm(self, monkeypatch):
        winner = decision_pipeline.Candidate("silence", None, None)
        _stub_pipeline(monkeypatch, winner=winner, audit=_silence_audit())
        run = _run(RUN_KIND_AUTONOMOUS_TICK)

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_AUTONOMOUS_TICK),
            trigger_intention="share_own_feeling",
            run=run,
            now=NOW,
        )

        assert intention.llm_used is False
        assert intention.degraded is True
        assert intention.source == "silence"
        assert run.degraded is True

    async def test_denied_other_candidate_does_not_degrade_winner(self, monkeypatch):
        winner = decision_pipeline.Candidate("chat_response", "continue_topic", None)
        audit = _silence_audit()
        audit["candidates"][0]["won"] = False
        audit["candidates"][1] = {
            "source": "chat_response",
            "intention": "continue_topic",
            "goal_id": None,
            "priority": "P0",
            "scores": {},
            "total": 0.9,
            "gates": [{"budget_cooldown": "pass", "reason": "ok"}],
            "won": True,
        }
        _stub_pipeline(monkeypatch, winner=winner, audit=audit)
        run = _run()

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=run,
            now=NOW,
        )

        assert intention.llm_used is True
        assert intention.degraded is False
        assert run.degraded is False

    async def test_reason_does_not_call_gateway_directly(self, monkeypatch):
        from app.application.agent_runtime import llm_gateway

        calls: list = []
        monkeypatch.setattr(
            llm_gateway, "acquire", lambda *args, **kwargs: calls.append(args)
        )
        _stub_pipeline(monkeypatch)

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert calls == []


class TestDegradation:
    pytestmark = pytest.mark.unit

    async def test_stack_failure_degrades_not_raise(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("stack down")

        monkeypatch.setattr(goal_stack_service, "evaluate_stack", _boom)
        calls, _ = _stub_pipeline(monkeypatch)

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert intention.degraded_fact_sets() == (FACT_SET_GOAL_STACK,)
        assert calls[-1]["stack"] is None

    async def test_world_and_insight_failure_degrades_not_raise(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr(world_engine, "collect_facts", _boom)
        monkeypatch.setattr(autonomy_engine, "collect_tool_insights", _boom)
        calls, _ = _stub_pipeline(monkeypatch)

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert set(intention.degraded_fact_sets()) == {
            FACT_SET_WORLD,
            FACT_SET_TOOL_INSIGHTS,
        }
        assert calls[-1]["world_impacts"] is None
        assert calls[-1]["tool_insights"] is None

    async def test_snapshot_failure_degrades_not_raise(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("state down")

        monkeypatch.setattr(state_manager, "snapshot", _boom)
        calls, _ = _stub_pipeline(monkeypatch)

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert intention.degraded_fact_sets() == (FACT_SET_SNAPSHOT,)
        assert calls[-1]["snapshot"] is None

    async def test_trace_records_intention(self, monkeypatch):
        from app.services.observability.collector import TurnTraceSession

        _stub_pipeline(monkeypatch)
        trace = TurnTraceSession()

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
            trace=trace,
        )

        step = trace.steps[-1]
        assert step.name == reason_module.TRACE_STAGE
        assert step.status == "ok"
        assert step.extra["source"] == "chat_response"
        assert step.extra["llm_used"] is True


class TestEventEmission:
    pytestmark = pytest.mark.unit

    async def test_decision_made_event_emitted(self, monkeypatch, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_DECISION_MADE, captured.append)
        override_settings(runtime_event_bus_enabled="true")
        _stub_pipeline(monkeypatch)

        intention = await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert len(captured) == 1
        assert captured[0].run_id == "r-reason"
        assert captured[0].payload["source"] == intention.source
        assert captured[0].payload["llm_used"] is True

    async def test_event_silent_when_flag_off(self, monkeypatch, override_settings):
        captured: list = []
        event_bus.subscribe(EVENT_DECISION_MADE, captured.append)
        override_settings(runtime_event_bus_enabled="false")
        _stub_pipeline(monkeypatch)

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert captured == []


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_reason_module_has_no_forbidden_imports(self):
        tree = ast.parse(REASON_PATH.read_text(encoding="utf-8"))
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

    def test_reason_module_performs_no_writes(self):
        source = REASON_PATH.read_text(encoding="utf-8")

        assert not any(token in source for token in FORBIDDEN_WRITE_TOKENS)

    def test_build_stack_is_read_only_by_default(self, monkeypatch):
        captured: list = []
        monkeypatch.setattr(
            goal_stack_service,
            "evaluate_stack",
            lambda user_id, now=None, retire_overdue_enabled=True: captured.append(
                retire_overdue_enabled
            ),
        )

        build_stack("u1", now=NOW)

        assert captured == [False]

    async def test_reason_never_calls_retire_overdue(self, monkeypatch):
        called: list = []
        monkeypatch.setattr(
            goal_stack_service, "retire_overdue", lambda *a, **k: called.append(a)
        )
        _stub_pipeline(monkeypatch)

        await reason(
            None,
            _session(),
            _observation(),
            spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
            run=_run(),
            now=NOW,
        )

        assert called == []

    def test_intention_is_frozen(self):
        intention = Intention(
            intention=None,
            goal_id=None,
            source="silence",
            priority=None,
            confidence=None,
            llm_used=False,
            degraded=False,
            audit={},
            decided_at=NOW,
        )

        with pytest.raises(dataclasses.FrozenInstanceError):
            intention.source = "chat_response"


class TestIntegration:
    pytestmark = pytest.mark.integration

    async def test_reason_reads_real_surfaces_without_writes(self, db_session_factory):
        from sqlalchemy import event as sqlalchemy_event
        from sqlalchemy.orm import Session

        touched: list[str] = []

        def _before_flush(session, flush_context, instances):
            for obj in list(session.new) + list(session.dirty) + list(session.deleted):
                touched.append(type(obj).__tablename__)

        run = _run()
        sqlalchemy_event.listen(Session, "before_flush", _before_flush)
        try:
            intention = await reason(
                None,
                _session(),
                _observation(),
                spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
                run=run,
                now=NOW,
            )
        finally:
            sqlalchemy_event.remove(Session, "before_flush", _before_flush)

        assert isinstance(intention, Intention)
        assert touched == []

    async def test_decision_records_not_written_by_reason(self, db_session_factory):
        from app.repositories import decision_repository

        def _boom(*args, **kwargs):
            raise AssertionError("Reason 段不得直写 decision_records")

        original = decision_repository.save
        decision_repository.save = _boom
        try:
            intention = await reason(
                None,
                _session(),
                _observation(),
                spec=get_profile(RUN_KIND_FOREGROUND_CHAT),
                run=_run(),
                now=NOW,
            )
        finally:
            decision_repository.save = original

        assert isinstance(intention, Intention)
