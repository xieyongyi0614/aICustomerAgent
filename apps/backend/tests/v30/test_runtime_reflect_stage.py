"""RT-011 Reflection Stage（Reflect 段 / 慢时钟）测试：门控 / 幂等 / 预算 / 零写。"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.application.agent_runtime import events as event_bus  # noqa: F401  (进程态隔离锚)
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
    RunContext,
)
from app.application.agent_runtime.session import build_session_context
from app.application.agent_runtime.stages import reflect as reflect_module
from app.application.agent_runtime.stages.reflect import (
    REASON_BUDGET,
    REASON_DISABLED,
    REASON_DUPLICATE,
    REASON_NO_EVIDENCE,
    REASON_OPTIONAL_DISABLED,
    InsightRef,
    ReflectOutcome,
    evidence_window_key,
    reflect,
    reflect_enabled,
)
from app.models.reflection import Insight
from app.services.reflection import triggers

REFLECT_PATH = Path(reflect_module.__file__)
FORBIDDEN_IMPORTS = (
    "app.chains",
    "app.prompts",
    "app.channels.feishu",
    "app.services.memory2.job_worker",
)
FORBIDDEN_DIRECT_WRITE_TOKENS = (
    "InsightRow",
    "ReflectionRunRow",
    "EvidenceLinkRow",
    "SessionLocal",
    "notify_insight_created_listeners",
)
FORBIDDEN_SCHEDULER_TOKENS = (
    "register_job_type",
    "run_reflection_trigger_tick",
    "register_with_job_worker",
)

NOW = datetime(2026, 9, 21, 12, 0, 0)
USER_ID = "u-reflect"
SESSION_ID = "S-reflect"


@pytest.fixture(autouse=True)
def _reset_trigger_state():
    triggers.reset_trigger_state()
    yield
    triggers.reset_trigger_state()


def _run(run_kind=RUN_KIND_AUTONOMOUS_TICK, user_id=USER_ID):
    return RunContext(
        run_id="r-reflect",
        user_id=user_id,
        run_kind=run_kind,
        trigger_type="schedule",
        reason="rt011",
        started_at=NOW,
    )


def _session(**overrides):
    return build_session_context(SESSION_ID, channel="web", now=NOW, **overrides)


def _insight(insight_id="ins:1", *, created_at=NOW, insight_type="pattern", confidence=0.7):
    return Insight(
        id=insight_id,
        user_id=USER_ID,
        statement="用户在夜里更容易接受提醒",
        type=insight_type,
        confidence=confidence,
        scope="user",
        created_at=created_at,
        updated_at=created_at,
    )


def _stub_trigger(monkeypatch, outcome=triggers.OUTCOME_QUEUED):
    calls: list = []

    def _trigger_for_user(user_id, character_id="asuna", trigger="scheduled", now=None, trace=None, *, channel="memory"):
        calls.append({"user_id": user_id, "trigger": trigger, "now": now})
        return outcome

    monkeypatch.setattr(triggers, "trigger_for_user", _trigger_for_user)
    return calls


def _stub_reflector(monkeypatch, processed=1, *, raises=None):
    calls: list = []

    def _run_queued_reflections(now=None, trace=None):
        calls.append({"now": now})
        if raises is not None:
            raise raises
        return processed

    from app.services.reflection import reflector

    monkeypatch.setattr(reflector, "run_queued_reflections", _run_queued_reflections)
    return calls


def _stub_insights(monkeypatch, insights):
    from app.services.reflection import lifecycle

    monkeypatch.setattr(
        lifecycle, "list_active_insights", lambda *args, **kwargs: list(insights)
    )


def _stub_budget(monkeypatch, *, degraded=False, granted=True):
    from app.application.agent_runtime import llm_gateway
    from app.services import life_loop_budget

    monkeypatch.setattr(life_loop_budget, "is_degraded", lambda now=None: degraded)
    monkeypatch.setattr(
        llm_gateway,
        "acquire",
        lambda *args, **kwargs: llm_gateway.Grant(granted, False, "ok" if granted else "denied"),
    )


_DEFAULT_SESSION = object()


def _run_reflect(*, run=None, trace=None, action_outcome=None, session=_DEFAULT_SESSION):
    resolved_session = _session() if session is _DEFAULT_SESSION else session
    return asyncio.run(
        reflect(
            action_outcome=action_outcome,
            session_context=resolved_session,
            run=run or _run(),
            now=NOW,
            trace=trace,
        )
    )


class TestGating:
    pytestmark = pytest.mark.unit

    def test_reflect_disabled_by_default(self, monkeypatch):
        trigger_calls = _stub_trigger(monkeypatch)
        reflector_calls = _stub_reflector(monkeypatch)

        outcome = _run_reflect()

        assert reflect_enabled() is False
        assert outcome.triggered is False
        assert outcome.skipped_reason == REASON_DISABLED
        assert outcome.insights == ()
        assert outcome.llm_used is False
        assert trigger_calls == []
        assert reflector_calls == []

    def test_reflect_requires_optional_phase(self, monkeypatch, override_settings):
        override_settings(runtime_reflect_in_loop_enabled="true")
        trigger_calls = _stub_trigger(monkeypatch)
        reflector_calls = _stub_reflector(monkeypatch)

        outcome = _run_reflect()

        assert reflect_enabled() is True
        assert outcome.triggered is False
        assert outcome.skipped_reason == REASON_OPTIONAL_DISABLED
        assert trigger_calls == []
        assert reflector_calls == []

    def test_reflect_runs_when_flag_and_optional_phase_on(
        self, monkeypatch, override_settings
    ):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        trigger_calls = _stub_trigger(monkeypatch)
        reflector_calls = _stub_reflector(monkeypatch, processed=1)
        _stub_insights(monkeypatch, [_insight()])

        outcome = _run_reflect()

        assert len(trigger_calls) == 1
        assert trigger_calls[0]["trigger"] == triggers.TRIGGER_EVENT
        assert len(reflector_calls) == 1
        assert outcome.triggered is True
        assert outcome.skipped_reason is None
        assert outcome.llm_used is True

    def test_missing_identity_skips(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        trigger_calls = _stub_trigger(monkeypatch)

        outcome = _run_reflect(run=_run(user_id=None), session=None)

        assert outcome.triggered is False
        assert trigger_calls == []


class TestIdempotence:
    pytestmark = pytest.mark.unit

    def test_reflect_idempotent_within_window(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch, triggers.OUTCOME_QUOTA)
        reflector_calls = _stub_reflector(monkeypatch)

        outcome = _run_reflect()

        assert outcome.triggered is False
        assert outcome.skipped_reason == REASON_DUPLICATE
        assert outcome.insights == ()
        assert reflector_calls == []

    def test_no_passing_evidence_skips(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch, triggers.OUTCOME_SKIPPED)
        reflector_calls = _stub_reflector(monkeypatch)

        outcome = _run_reflect()

        assert outcome.skipped_reason == REASON_NO_EVIDENCE
        assert reflector_calls == []

    def test_trigger_off_maps_to_disabled(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch, triggers.OUTCOME_OFF)

        outcome = _run_reflect()

        assert outcome.skipped_reason == REASON_DISABLED
        assert outcome.triggered is False

    def test_evidence_window_key_reuses_triggers_bucket(self):
        assert evidence_window_key(USER_ID, NOW) == triggers._day_bucket_key(USER_ID, NOW)
        assert evidence_window_key(USER_ID, NOW) == f"reflect:{USER_ID}:2026-09-21"


class TestBudget:
    pytestmark = pytest.mark.unit

    def test_budget_exhausted_skips_without_raise(
        self, monkeypatch, override_settings
    ):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch, degraded=True)
        trigger_calls = _stub_trigger(monkeypatch)
        reflector_calls = _stub_reflector(monkeypatch)
        run = _run()

        outcome = _run_reflect(run=run)

        assert outcome.triggered is False
        assert outcome.skipped_reason == REASON_BUDGET
        assert outcome.degraded() is True
        assert outcome.llm_used is False
        assert run.degraded is True
        assert trigger_calls == []
        assert reflector_calls == []

    def test_gateway_denied_skips_with_budget(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch, granted=False)
        trigger_calls = _stub_trigger(monkeypatch)
        run = _run()

        outcome = _run_reflect(run=run)

        assert outcome.skipped_reason == REASON_BUDGET
        assert outcome.degraded() is True
        assert run.degraded is True
        assert trigger_calls == []

    def test_executor_failure_degrades_not_raise(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch)
        _stub_reflector(monkeypatch, raises=RuntimeError("executor down"))
        run = _run()

        outcome = _run_reflect(run=run)

        assert outcome.triggered is True
        assert outcome.degraded() is True
        assert run.degraded is True
        assert outcome.insights == ()


class TestProjection:
    pytestmark = pytest.mark.unit

    def test_insights_projected_to_refs(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch)
        _stub_reflector(monkeypatch)
        _stub_insights(
            monkeypatch,
            [_insight("ins:1"), _insight("ins:2", insight_type="preference", confidence=0.55)],
        )

        outcome = _run_reflect()

        assert outcome.insights == (
            InsightRef(
                insight_id="ins:1",
                insight_type="pattern",
                confidence=0.7,
                summary="用户在夜里更容易接受提醒",
            ),
            InsightRef(
                insight_id="ins:2",
                insight_type="preference",
                confidence=0.55,
                summary="用户在夜里更容易接受提醒",
            ),
        )

    def test_stale_insights_are_excluded(self, monkeypatch, override_settings):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch)
        _stub_reflector(monkeypatch)
        _stub_insights(
            monkeypatch,
            [
                _insight("ins:old", created_at=datetime(2026, 9, 20, 8, 0, 0)),
                _insight("ins:new"),
            ],
        )

        outcome = _run_reflect()

        assert [item.insight_id for item in outcome.insights] == ["ins:new"]

    def test_insight_projection_failure_degrades_to_empty(
        self, monkeypatch, override_settings
    ):
        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch)
        _stub_reflector(monkeypatch)
        from app.services.reflection import lifecycle

        def _boom(*args, **kwargs):
            raise RuntimeError("read down")

        monkeypatch.setattr(lifecycle, "list_active_insights", _boom)

        outcome = _run_reflect()

        assert outcome.triggered is True
        assert outcome.insights == ()


class TestBoundaries:
    pytestmark = pytest.mark.unit

    def test_reflect_module_has_no_forbidden_imports(self):
        tree = ast.parse(REFLECT_PATH.read_text(encoding="utf-8"))
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

    def test_reflect_does_not_write_insight_tables_directly(self):
        source = REFLECT_PATH.read_text(encoding="utf-8")

        assert not any(token in source for token in FORBIDDEN_DIRECT_WRITE_TOKENS)

    def test_reflect_adds_no_scheduler(self):
        source = REFLECT_PATH.read_text(encoding="utf-8")

        assert not any(token in source for token in FORBIDDEN_SCHEDULER_TOKENS)

    def test_reflect_outcome_is_frozen(self, monkeypatch):
        outcome = _run_reflect()

        with pytest.raises(dataclasses.FrozenInstanceError):
            outcome.triggered = True


class TestIntegration:
    pytestmark = pytest.mark.integration

    def test_no_duplicate_insights_across_loop_and_periodic(
        self, db_session_factory, monkeypatch, override_settings
    ):
        """同窗第二次必须 `duplicate_window`：不重复执行反思，Insight 行数不增加。"""
        from app.core.db import Base

        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_insights(monkeypatch, [])
        reflector_calls = _stub_reflector(monkeypatch, processed=1)
        # 有状态桩：镜像既有 triggers 的同窗去重（首次 queued，其后 quota）
        state = {"queued": False}

        def _trigger_for_user(
            user_id,
            character_id="asuna",
            trigger="scheduled",
            now=None,
            trace=None,
            *,
            channel="memory",
        ):
            if state["queued"]:
                return triggers.OUTCOME_QUOTA
            state["queued"] = True
            return triggers.OUTCOME_QUEUED

        monkeypatch.setattr(triggers, "trigger_for_user", _trigger_for_user)

        def _insight_rows():
            with db_session_factory() as session:
                return session.query(Base.metadata.tables["insights"]).count()

        before = _insight_rows()
        first = _run_reflect()
        after_first = _insight_rows()
        second = _run_reflect()
        after_second = _insight_rows()

        assert first.triggered is True
        assert second.triggered is False
        assert second.skipped_reason == REASON_DUPLICATE
        assert second.insights == ()
        assert len(reflector_calls) == 1
        assert before == after_first == after_second

    def test_real_trigger_never_queues_without_evidence(
        self, db_session_factory, override_settings, monkeypatch
    ):
        """真实 triggers 路径：无合格证据窗 → 不排队，段零执行（不绕过既有去重）。"""
        from app.services.reflection import reflector

        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        calls: list = []
        monkeypatch.setattr(
            reflector,
            "run_queued_reflections",
            lambda now=None, trace=None: calls.append(now) or 0,
        )

        outcome = _run_reflect()

        assert outcome.triggered is False
        assert outcome.skipped_reason in (REASON_NO_EVIDENCE, REASON_DUPLICATE)
        assert calls == []

    def test_real_trigger_writes_only_reflection_runs(
        self, db_session_factory, override_settings, monkeypatch
    ):
        """真实 triggers 路径的写面 ⊆ `reflection_runs`（触发器的 run 台账）。"""
        from sqlalchemy import event as sqlalchemy_event
        from sqlalchemy.orm import Session
        from app.services.reflection import reflector

        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        monkeypatch.setattr(
            reflector, "run_queued_reflections", lambda now=None, trace=None: 0
        )
        touched: list[str] = []

        def _before_flush(session, flush_context, instances):
            for obj in list(session.new) + list(session.dirty) + list(session.deleted):
                touched.append(type(obj).__tablename__)

        sqlalchemy_event.listen(Session, "before_flush", _before_flush)
        try:
            _run_reflect()
        finally:
            sqlalchemy_event.remove(Session, "before_flush", _before_flush)

        assert set(touched) <= {"reflection_runs"}

    def test_reflect_writes_nothing_when_executor_stubbed(
        self, db_session_factory, monkeypatch, override_settings
    ):
        from sqlalchemy import event as sqlalchemy_event
        from sqlalchemy.orm import Session

        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        _stub_budget(monkeypatch)
        _stub_trigger(monkeypatch)
        _stub_reflector(monkeypatch)
        _stub_insights(monkeypatch, [])
        touched: list[str] = []

        def _before_flush(session, flush_context, instances):
            for obj in list(session.new) + list(session.dirty) + list(session.deleted):
                touched.append(type(obj).__tablename__)

        sqlalchemy_event.listen(Session, "before_flush", _before_flush)
        try:
            _run_reflect()
        finally:
            sqlalchemy_event.remove(Session, "before_flush", _before_flush)

        assert touched == []

    async def test_loop_reflect_method_delegates_to_rt011_stage(
        self, db_session_factory, override_settings
    ):
        from app.application import agent_runtime
        from app.application.agent_runtime.loop import AgentLoop
        from app.application.agent_runtime.profiles import get_profile

        override_settings(
            runtime_reflect_in_loop_enabled="true", runtime_loop_optional_stages="reflect"
        )
        spec = get_profile(RUN_KIND_AUTONOMOUS_TICK)
        run = agent_runtime.open_run(
            "u-loop-reflect", RUN_KIND_AUTONOMOUS_TICK, "schedule", "rt011", NOW
        )
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry={})
        loop.session_context = _session()
        loop.act_outcome = SimpleNamespace(action_id="a-1", result=SimpleNamespace(status="succeeded"))

        outcome = await loop.reflect()

        assert isinstance(outcome, ReflectOutcome)
        assert loop.reflect_outcome is outcome

    async def test_loop_reflect_disabled_returns_outcome(
        self, db_session_factory
    ):
        from app.application import agent_runtime
        from app.application.agent_runtime.loop import AgentLoop
        from app.application.agent_runtime.profiles import get_profile

        spec = get_profile(RUN_KIND_FOREGROUND_CHAT)
        run = agent_runtime.open_run(
            "u-loop-reflect-off", RUN_KIND_FOREGROUND_CHAT, "channel_message", "rt011", NOW
        )
        loop = AgentLoop(spec, user_id=run.user_id, run=run, now=NOW, registry={})

        outcome = await loop.reflect()

        assert isinstance(outcome, ReflectOutcome)
        assert outcome.skipped_reason == REASON_DISABLED
