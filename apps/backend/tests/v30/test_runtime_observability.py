"""RT-019 Runtime Observability 测试：段级 Debug / 因果链 / 只读回放 / 零写入。"""

from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.application import observability
from app.application.agent_runtime import debug_view as debug_view_module
from app.application.agent_runtime import execution_history
from app.application.agent_runtime.controller import open_run
from app.application.agent_runtime.loop import AgentLoop, stage_phase
from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_FOREGROUND_CHAT,
)
from app.application.agent_runtime.profiles import get_profile
from app.core.db import (
    ActionRecordRow,
    AgentStateSnapshotRow,
    DecisionRecordRow,
    LoopRunRow,
    RuntimeTraceRow,
)
from app.models.action import ActionRecord
from app.models.observability import DecisionKind, DecisionRecord, RuntimeTrace, TraceKind
from app.repositories import (
    action_repository,
    agent_state_snapshot_repository,
    decision_repository,
    loop_run_repository,
    trace_repository,
)
from app.services.observability import trace_query
from app.services.observability.collector import TurnTraceSession

QUERY_PATH = Path(trace_query.__file__)
FACADE_PATH = Path(debug_view_module.__file__)
FORBIDDEN = (
    "app.chains",
    "app.prompts",
    "app.channels",
    "app.api",
    "app.core.db",
    "app.application",
    "agent_evaluation",
    "evaluation_rules",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _identifiers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _trace_row(
    db_session_factory,
    trace_id: str,
    *,
    user_id: str,
    correlation_id: str | None,
    action_id: str | None = None,
    age_days: int = 0,
) -> None:
    created = datetime.now() - timedelta(days=age_days)
    with db_session_factory() as session:
        session.add(
            RuntimeTraceRow(
                id=trace_id,
                kind="turn",
                user_id=user_id,
                conversation_id=None,
                turn_id=trace_id,
                action_id=action_id,
                correlation_id=correlation_id,
                status="complete",
                started_at=created,
                duration_ms=1.0,
                steps=[],
                events=[],
                token_usage={},
                model_name=None,
                meta={},
                created_at=created,
            )
        )
        session.commit()


def _action(
    record_id: str, *, run_id: str | None, user_id: str, session_id: str | None = None
) -> ActionRecord:
    now = datetime.now()
    return action_repository.save_record(
        ActionRecord(
            id=record_id,
            user_id=user_id,
            character_id="asuna",
            session_id=session_id,
            run_id=run_id,
            source="conversation",
            action_type="create_reminder",
            intent={"content": "x"},
            goal_id=None,
            target_record_id=None,
            dedupe_key=f"dedupe-{record_id}",
            params={},
            status="succeeded",
            gate_reason=None,
            steps=[],
            result={"ok": True},
            attempt=1,
            priority=100,
            next_retry_at=None,
            scheduled_at=None,
            created_at=now,
            updated_at=now,
            executed_at=now,
        )
    )


def _decision(
    record_id: str, *, user_id: str, action_id: str | None, request_id: str | None
) -> DecisionRecord:
    record = DecisionRecord(
        id=record_id,
        kind=DecisionKind.TURN_INTENTION,
        request_id=request_id,
        user_id=user_id,
        conversation_id=None,
        action_id=action_id,
        trigger="test",
        input_snapshot={},
        decision="continue_topic",
        reason="test",
        confidence=0.9,
        outcome=None,
        candidates=None,
        created_at=datetime.now(),
    )
    decision_repository.save(record)
    return record


def _flush(
    trace,
    *,
    turn_id: str,
    user_id: str,
    session_id: str,
    monkeypatch,
    correlation_id: str | None = None,
) -> None:
    """走公开落库链路（`on_turn_finished`），并等待 write-behind 任务完成。"""
    monkeypatch.setattr(observability, "_main_loop", None)

    async def _run():
        token = observability.bind_correlation_id(correlation_id)
        try:
            observability.on_turn_finished(
                trace, turn_id, user_id, session_id, drain_background=False
            )
        finally:
            observability.reset_correlation_id(token)
        pending = [
            task for task in list(observability.background_tasks) if not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(_run())


def _stub_registry(stages, *, failures=()):
    calls: list[str] = []
    registry: dict[str, object] = {}
    for name in stages:

        def _make(stage=name):
            async def _run(context):
                calls.append(stage)
                if stage in failures:
                    raise RuntimeError(f"boom:{stage}")
                return {"status": "ok"}

            return _run

        registry[name] = _make()
    return calls, registry


async def _drive_loop(
    run_kind: str,
    *,
    user_id: str,
    session_id: str | None = None,
    failures=(),
):
    run = open_run(
        user_id, run_kind, "channel_message", "rt019", session_id=session_id
    )
    spec = get_profile(run_kind)
    calls, registry = _stub_registry(spec.stages, failures=failures)
    loop = AgentLoop(spec, user_id=user_id, run=run, registry=registry)
    result = await loop.run()
    return run, result, calls


class TestDebugView:
    pytestmark = pytest.mark.unit

    def test_by_run_id_returns_full_stage_sequence(self, db_session_factory):
        steps = [
            {"step": "perception", "status": "ok", "duration_ms": 3.0},
            {"step": "turn_decisions", "status": "ok", "duration_ms": 5.0},
            {"step": "record_handoff", "status": "ok", "duration_ms": 1.0},
        ]
        run = loop_run_repository.create_run(
            user_id="u-dbg",
            kind="chat",
            reason="rt019",
            trigger_type="channel_message",
            session_id="S-dbg",
            run_kind=RUN_KIND_FOREGROUND_CHAT,
        )
        for step in steps:
            loop_run_repository.mark_step(run.id, step)
        loop_run_repository.finish_run(
            run.id,
            status="done",
            steps=steps,
            llm_call_count=2,
            token_total=120,
            budget_state={"status": "ok"},
        )

        view = debug_view_module.debug_view(run.id)

        assert view is not None
        assert [stage["step"] for stage in view.stages] == [
            step["step"] for step in steps
        ]
        assert [stage["duration_ms"] for stage in view.stages] == [3.0, 5.0, 1.0]
        assert [stage["status"] for stage in view.stages] == ["ok", "ok", "ok"]
        assert [stage["phase"] for stage in view.stages] == [
            "observe",
            "reason",
            "update",
        ]
        assert view.run_kind == RUN_KIND_FOREGROUND_CHAT
        assert view.trigger_type == "channel_message"
        assert view.llm_call_count == 2
        assert view.budget_state == {"status": "ok"}
        assert view.correlation_id == run.id
        assert debug_view_module.debug_view("missing-run") is None

    def test_by_session_returns_ordered_runs(self, db_session_factory):
        base = datetime.now() - timedelta(hours=2)
        created: list[str] = []
        for offset in (30, 0, 15):
            row = loop_run_repository.create_run(
                user_id="u-sess",
                kind="chat",
                reason="rt019",
                session_id="S-ordered",
                now=base + timedelta(minutes=offset),
            )
            loop_run_repository.finish_run(
                row.id, status="done", now=base + timedelta(minutes=offset + 1)
            )
            created.append(row.id)

        views = debug_view_module.debug_views_for_session("S-ordered")

        assert [view.run_id for view in views] == [created[1], created[2], created[0]]
        assert [view.started_at for view in views] == sorted(
            view.started_at for view in views
        )
        assert debug_view_module.debug_views_for_session("S-empty") == []

    def test_debug_view_includes_degradation_reason(self, db_session_factory):
        steps = [
            {"step": "perception", "status": "ok", "duration_ms": 1.5},
            {
                "step": "reply_generation",
                "status": "error",
                "error": "RuntimeError",
                "duration_ms": 2.0,
            },
        ]
        run = loop_run_repository.create_run(
            user_id="u-deg", kind="chat", reason="rt019-deg", session_id="S-deg"
        )
        for step in steps:
            loop_run_repository.mark_step(run.id, step)
        loop_run_repository.finish_run(run.id, status="degraded", steps=steps)

        view = debug_view_module.debug_view(run.id)

        assert view is not None
        assert view.degraded is True
        failed = view.failed_stages
        assert len(failed) == 1
        assert failed[0]["step"] == "reply_generation"
        assert failed[0]["error"] == "RuntimeError"
        assert failed[0]["phase"] == "act"
        assert failed[0]["error_kind"] == "execution"

    def test_unknown_stage_is_marked_missing(self, db_session_factory):
        run = loop_run_repository.create_run(
            user_id="u-pseudo", kind="chat", reason="rt019-pseudo"
        )
        loop_run_repository.mark_step(
            run.id, {"step": "orphan_sweep", "status": "error", "error": "orphan_timeout"}
        )

        view = debug_view_module.debug_view(run.id)

        assert view is not None
        assert view.stages[0]["phase"] is None
        assert view.stages[0]["error_kind"] is None
        assert view.degraded is True


class TestCorrelationChain:
    pytestmark = pytest.mark.unit

    def test_by_correlation_links_layers(self, db_session_factory):
        run = loop_run_repository.create_run(
            user_id="u-chain", kind="chat", reason="rt019", session_id="S-chain"
        )
        action = _action("act-chain", run_id=run.id, user_id="u-chain")
        _decision(
            "dec-chain", user_id="u-chain", action_id=action.id, request_id=run.id
        )
        _trace_row(
            db_session_factory,
            "tr-chain",
            user_id="u-chain",
            correlation_id=run.id,
            action_id=action.id,
        )

        entries = trace_query.by_correlation(run.id)

        assert {entry["layer"] for entry in entries} == {"trace", "decision", "action"}
        assert {entry["id"] for entry in entries} == {"tr-chain", "dec-chain", action.id}
        assert trace_query.by_correlation("missing-corr") == []

    def test_by_correlation_follows_action_id_from_trace(self, db_session_factory):
        action = _action("act-proactive", run_id=None, user_id="u-pro")
        _decision(
            "dec-proactive", user_id="u-pro", action_id=action.id, request_id=None
        )
        _trace_row(
            db_session_factory,
            "tr-proactive",
            user_id="u-pro",
            correlation_id="proactive:key-1",
            action_id=action.id,
        )

        entries = trace_query.by_correlation("proactive:key-1")

        assert {entry["layer"] for entry in entries} == {"trace", "decision", "action"}

    def test_correlation_id_written_on_flush(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(
            observability_persist_enabled="true",
            observability_trace_sample_rate="1.0",
        )
        trace = TurnTraceSession(user_id="u-corr", turn_id="t-corr")

        _flush(
            trace,
            turn_id="t-corr",
            user_id="u-corr",
            session_id="S-corr",
            monkeypatch=monkeypatch,
            correlation_id="run-corr",
        )

        stored = trace_repository.get_by_trace_id(trace.request_id)
        assert stored is not None
        assert stored.correlation_id == "run-corr"
        assert [row.id for row in trace_repository.list_by_correlation_id("run-corr")] == [
            trace.request_id
        ]

    def test_unbound_correlation_leaves_column_empty(
        self, db_session_factory, override_settings, monkeypatch
    ):
        override_settings(
            observability_persist_enabled="true",
            observability_trace_sample_rate="1.0",
        )
        trace = TurnTraceSession(user_id="u-none", turn_id="t-none")

        _flush(
            trace,
            turn_id="t-none",
            user_id="u-none",
            session_id="S-none",
            monkeypatch=monkeypatch,
        )

        stored = trace_repository.get_by_trace_id(trace.request_id)
        assert stored is not None
        assert stored.correlation_id is None


class TestReplayBundle:
    pytestmark = pytest.mark.unit

    def test_replay_bundle_is_read_only_and_complete(self, db_session_factory):
        run = loop_run_repository.create_run(
            user_id="u-replay", kind="chat", reason="rt019", session_id="S-replay"
        )
        action = _action(
            "act-replay", run_id=run.id, user_id="u-replay", session_id="S-replay"
        )
        _decision(
            "dec-replay", user_id="u-replay", action_id=action.id, request_id=run.id
        )
        _trace_row(
            db_session_factory,
            "tr-replay",
            user_id="u-replay",
            correlation_id=run.id,
            action_id=action.id,
        )
        agent_state_snapshot_repository.save(
            user_id="u-replay",
            snapshot={"id": "snap-replay"},
            version=1,
            run_id=run.id,
            now=datetime.now(),
        )
        loop_run_repository.finish_run(run.id, status="done")

        before = _row_counts(db_session_factory)
        bundle = debug_view_module.replay_bundle(run.id)
        after = _row_counts(db_session_factory)

        assert bundle is not None
        assert bundle.run_id == run.id
        assert bundle.snapshot_anchor is not None
        assert bundle.snapshot_anchor["run_id"] == run.id
        assert [item["id"] for item in bundle.decisions] == ["dec-replay"]
        assert [item["id"] for item in bundle.actions] == [action.id]
        assert [item["id"] for item in bundle.traces] == ["tr-replay"]
        assert before == after
        assert debug_view_module.replay_bundle("missing-run") is None

    def test_retention_and_sampling_unchanged(
        self, db_session_factory, override_settings, monkeypatch
    ):
        # 采样仍生效：rate=0 时即使绑定了 correlation_id 也不落库
        override_settings(
            observability_persist_enabled="true",
            observability_trace_sample_rate="0.0",
        )
        trace = TurnTraceSession(user_id="u-samp", turn_id="t-samp")
        _flush(
            trace,
            turn_id="t-samp",
            user_id="u-samp",
            session_id="S-samp",
            monkeypatch=monkeypatch,
            correlation_id="run-samp",
        )
        assert trace_repository.get_by_trace_id(trace.request_id) is None

        # 保留期仍生效：带 correlation_id 的行同样被 prune 清理
        _trace_row(
            db_session_factory,
            "tr-ret-old",
            user_id="u-samp",
            correlation_id="run-samp",
            age_days=10,
        )
        _trace_row(
            db_session_factory,
            "tr-ret-new",
            user_id="u-samp",
            correlation_id="run-samp",
            age_days=0,
        )

        deleted = trace_repository.prune_before(datetime.now() - timedelta(days=1))

        assert deleted == 1
        assert trace_repository.get_by_trace_id("tr-ret-old") is None
        assert trace_repository.get_by_trace_id("tr-ret-new") is not None


class TestQueryDiscipline:
    pytestmark = pytest.mark.unit

    def test_query_module_has_no_forbidden_imports(self):
        imported = _imported_modules(QUERY_PATH)
        offenders = [
            name
            for name in imported
            if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN)
        ]

        assert offenders == []
        assert "SessionLocal" not in _identifiers(QUERY_PATH)

    def test_services_query_layer_does_not_depend_on_runtime(self):
        """H-2 分层护栏：services 读面不得 import application.agent_runtime。"""
        imported = _imported_modules(QUERY_PATH)
        reverse = [
            name
            for name in imported
            if name == "app.application" or name.startswith("app.application.")
        ]

        assert reverse == []
        # 反向依赖必须由上层门面承担，且门面确实在 application 层
        assert "app.application.agent_runtime.execution_history" in _imported_modules(
            FACADE_PATH
        )
        assert "app.services.observability" in {
            name.rsplit(".", 1)[0] for name in _imported_modules(FACADE_PATH)
        }

    def test_query_surface_is_read_only(self, db_session_factory, monkeypatch):
        run = loop_run_repository.create_run(
            user_id="u-ro", kind="chat", reason="rt019-ro", session_id="S-ro"
        )
        _action("act-ro", run_id=run.id, user_id="u-ro")
        _trace_row(db_session_factory, "tr-ro", user_id="u-ro", correlation_id=run.id)

        def _boom(*_args, **_kwargs):
            raise AssertionError("观测查询不得触发写路径")

        for module, names in (
            (
                loop_run_repository,
                ("create_run", "mark_step", "finish_run"),
            ),
            (trace_repository, ("save", "prune_before")),
            (
                decision_repository,
                ("save", "mark_outcome", "prune_before"),
            ),
            (
                action_repository,
                (
                    "save_record",
                    "save_record_with_outbox",
                    "save_schedule",
                    "mark_schedule_executed",
                    "mark_schedule_cancelled",
                    "claim_due_schedule",
                    "retain_cleanup",
                ),
            ),
            (
                agent_state_snapshot_repository,
                ("save", "cleanup_expired"),
            ),
        ):
            for name in names:
                monkeypatch.setattr(module, name, _boom)

        assert debug_view_module.debug_view(run.id) is not None
        assert debug_view_module.debug_views_for_session("S-ro")
        assert trace_query.by_correlation(run.id)
        assert debug_view_module.replay_bundle(run.id) is not None

    def test_replay_bundle_delegates_to_execution_history(self):
        imported = _imported_modules(FACADE_PATH)

        assert "app.application.agent_runtime.execution_history" in imported
        assert callable(execution_history.history_for_run)


class TestFullChain:
    pytestmark = pytest.mark.integration

    def test_full_observability_chain_foreground(
        self, db_session_factory, override_settings
    ):
        override_settings(runtime_session_tracking_enabled="true")
        run, result, calls = asyncio.run(
            _drive_loop(RUN_KIND_FOREGROUND_CHAT, user_id="u-fg", session_id="S-fg")
        )

        view = debug_view_module.debug_view(run.run_id)

        assert view is not None
        assert result.status == "done"
        assert view.status == "done"
        assert view.session_id == "S-fg"
        assert [stage["step"] for stage in view.stages] == list(calls)
        assert [stage["phase"] for stage in view.stages] == [
            stage_phase(name) for name in calls
        ]
        assert all(float(stage["duration_ms"]) >= 0.0 for stage in view.stages)
        assert not view.degraded
        assert view.failed_stages == ()

    def test_full_observability_chain_background(
        self, db_session_factory, override_settings
    ):
        override_settings(runtime_session_tracking_enabled="true")
        run, result, calls = asyncio.run(
            _drive_loop(
                RUN_KIND_AUTONOMOUS_TICK,
                user_id="u-bg",
                session_id="S-bg",
                failures=("world_experience",),
            )
        )

        view = debug_view_module.debug_view(run.run_id)

        assert view is not None
        assert result.status == "degraded"
        assert view.status == "degraded"
        assert view.degraded is True
        assert [stage["step"] for stage in view.stages] == list(calls)
        failed = view.failed_stages
        assert len(failed) == 1
        assert failed[0]["step"] == "world_experience"
        assert failed[0]["error"] == "RuntimeError"
        assert failed[0]["phase"] == "update"
        assert failed[0]["error_kind"] == "state"


def _row_counts(db_session_factory) -> tuple[int, ...]:
    with db_session_factory() as session:
        return (
            session.query(RuntimeTraceRow).count(),
            session.query(LoopRunRow).count(),
            session.query(DecisionRecordRow).count(),
            session.query(ActionRecordRow).count(),
            session.query(AgentStateSnapshotRow).count(),
        )
