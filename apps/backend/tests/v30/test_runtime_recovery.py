"""RT-018 Runtime Persistence & Recovery 测试：孤儿回收 / 不重放 / 只读投影。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.core import timeutil
from app.application.agent_runtime import execution_history, recovery
from app.application.agent_runtime.controller import close_run, open_foreground_run
from app.core.db import (
    DevelopmentChangeRow,
    DevelopmentStateRow,
    RuntimeTraceRow,
)
from app.models.action import ActionRecord
from app.models.observability import DecisionKind, DecisionRecord
from app.models.relationship import RelationshipDelta, RelationshipEvent
from app.repositories import (
    action_repository,
    agent_state_snapshot_repository,
    decision_repository,
    loop_run_repository,
    relationship_event_repository,
)

RECOVERY_PATH = Path(recovery.__file__)
HISTORY_PATH = Path(execution_history.__file__)
FORBIDDEN = (
    "app.chains",
    "app.prompts",
    "app.channels.feishu",
    "action_engine",
    "memory_repository",
    "relationship_repository",
    "personality_state_repository",
    "world_repository",
    "goal_repository",
    "outbox_repository",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _offenders(path: Path) -> list[str]:
    imported = _imported_modules(path)
    return [
        name
        for name in imported
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN)
    ]


def _timed_out_run(user_id: str = "u-orphan", *, session_id: str | None = None, steps=None):
    row = loop_run_repository.create_run(
        user_id=user_id,
        kind="chat",
        reason="orphan-test",
        now=timeutil.now() - timedelta(hours=2),
        session_id=session_id,
    )
    if steps:
        for step in steps:
            loop_run_repository.mark_step(row.id, step)
    return row


def _fresh_run(user_id: str = "u-fresh"):
    return loop_run_repository.create_run(
        user_id=user_id,
        kind="chat",
        reason="fresh-test",
        now=timeutil.now(),
    )


def _action(record_id: str, *, run_id: str | None, user_id: str, session_id: str | None = None):
    now = timeutil.now()
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


def _decision(record_id: str, *, user_id: str, action_id: str | None, request_id: str | None):
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
        created_at=timeutil.now(),
    )
    decision_repository.save(record)
    return record


def _trace(db_session_factory, trace_id: str, *, user_id: str, correlation_id: str | None, action_id: str | None = None):
    now = timeutil.now()
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
                started_at=now,
                duration_ms=1.0,
                steps=[],
                events=[],
                token_usage={},
                model_name=None,
                meta={},
                created_at=now,
            )
        )
        session.commit()


def _development_change(db_session_factory, change_id: str, *, user_id: str):
    now = timeutil.now()
    with db_session_factory() as session:
        state = DevelopmentStateRow(
            id=f"dev-{change_id}",
            user_id=user_id,
            character_id="asuna",
            kind="belief",
            key="k",
            value={"v": 1},
            strength=0.5,
            source_insight_id="ins-1",
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(state)
        session.flush()
        session.add(
            DevelopmentChangeRow(
                id=change_id,
                development_state_id=state.id,
                personality_state_id=None,
                before={},
                after={"v": 1},
                insight_id="ins-1",
                reason="compiled",
                created_at=now,
            )
        )
        session.commit()


def _relationship_event(event_id: str, *, user_id: str, session_id: str):
    return relationship_event_repository.create_event(
        RelationshipEvent(
            id=event_id,
            user_id=user_id,
            character_id="asuna",
            session_id=session_id,
            type="warm_moment",
            magnitude="weak",
            impact=RelationshipDelta(
                intimacy=0.01,
                trust=0.01,
                familiarity=0.0,
                respect=0.0,
                comfort=0.0,
                tension=0.0,
            ),
            confidence=0.8,
            source="conversation",
            cause="test",
            created_at=timeutil.now(),
        )
    )


def _snapshot(snapshot_id: str, *, user_id: str, run_id: str | None):
    return agent_state_snapshot_repository.save(
        user_id=user_id,
        snapshot={"id": snapshot_id},
        version=1,
        run_id=run_id,
        now=timeutil.now(),
    )


def test_sweep_converges_timed_out_running_run(db_session_factory):
    run = _timed_out_run(steps=[{"step": "observe", "status": "ok"}])

    swept = recovery.sweep_orphan_runs()

    assert run.id in swept
    row = loop_run_repository.get(run.id)
    assert row.status == "aborted"
    assert row.finished_at is not None
    steps = list(row.steps or [])
    assert steps[0] == {"step": "observe", "status": "ok"}
    assert steps[-1] == {
        "step": "orphan_sweep",
        "status": "error",
        "error": "orphan_timeout",
    }


def test_sweep_is_idempotent(db_session_factory):
    run = _timed_out_run()
    first = recovery.sweep_orphan_runs()
    second = recovery.sweep_orphan_runs()

    assert first == [run.id]
    assert second == []
    row = loop_run_repository.get(run.id)
    assert row.status == "aborted"
    assert sum(1 for s in row.steps if s.get("step") == "orphan_sweep") == 1


def test_sweep_skips_recent_runs(db_session_factory):
    run = _fresh_run()

    swept = recovery.sweep_orphan_runs()

    assert run.id not in swept
    assert loop_run_repository.get(run.id).status == "running"


def test_sweep_disabled_by_setting(db_session_factory, override_settings):
    override_settings(runtime_orphan_run_sweep_enabled="false")
    run = _timed_out_run()

    swept = recovery.sweep_orphan_runs()

    assert swept == []
    assert loop_run_repository.get(run.id).status == "running"


def test_no_replay_on_restart(db_session_factory):
    run = _timed_out_run()
    pending = recovery.pending_orphan_ids()

    assert run.id in pending
    assert loop_run_repository.get(run.id).status == "running"
    recovered = recovery.sweep_orphan_runs()
    assert recovered == [run.id]
    assert recovery.sweep_orphan_runs() == []
    assert loop_run_repository.get(run.id).status == "aborted"


def test_resume_yields_next_run_not_partial(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="true")
    run = open_foreground_run("u-resume-partial", session_id="S-partial")
    close_run(run, "done")

    context = recovery.resume_session_context("S-partial")

    assert context is not None
    assert context.session_id == "S-partial"
    assert context.run_id == run.run_id
    assert not hasattr(context, "steps")
    assert not hasattr(context, "current_step")


def test_history_aggregates_all_layers(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="true")
    run = open_foreground_run("u-hist", session_id="S-hist")
    action = _action("act-hist", run_id=run.run_id, user_id="u-hist", session_id="S-hist")
    _decision("dec-hist", user_id="u-hist", action_id=action.id, request_id=run.run_id)
    _trace(
        db_session_factory,
        "tr-hist",
        user_id="u-hist",
        correlation_id=run.run_id,
        action_id=action.id,
    )
    _development_change(db_session_factory, "devchg-hist", user_id="u-hist")
    _relationship_event("rel-hist", user_id="u-hist", session_id="S-hist")
    _snapshot("snap-hist", user_id="u-hist", run_id=run.run_id)
    close_run(run, "done")

    history = execution_history.history_for_run(run.run_id)

    assert history is not None
    assert history.run_id == run.run_id
    assert history.run["id"] == run.run_id
    assert len(history.traces) >= 1
    assert len(history.decisions) >= 1
    assert len(history.actions) == 1
    assert history.actions[0]["id"] == action.id
    assert len(history.state_changes) >= 1
    assert history.snapshot_anchor is not None
    assert history.snapshot_anchor["run_id"] == run.run_id


def test_history_is_read_only(db_session_factory, override_settings, monkeypatch):
    override_settings(runtime_session_tracking_enabled="true")
    run = open_foreground_run("u-ro", session_id="S-ro")
    close_run(run, "done")

    def _boom(*_args, **_kwargs):
        raise AssertionError("执行历史查询不得触发写路径")

    for name in ("create_run", "mark_step", "finish_run"):
        monkeypatch.setattr(loop_run_repository, name, _boom)
    monkeypatch.setattr(action_repository, "save_record", _boom)
    monkeypatch.setattr(decision_repository, "save", _boom)
    monkeypatch.setattr(decision_repository, "mark_outcome", _boom)
    monkeypatch.setattr(decision_repository, "prune_before", _boom)
    monkeypatch.setattr(relationship_event_repository, "create_event", _boom)
    monkeypatch.setattr(agent_state_snapshot_repository, "save", _boom)
    monkeypatch.setattr(agent_state_snapshot_repository, "cleanup_expired", _boom)

    history = execution_history.history_for_run(run.run_id)
    assert history is not None


def test_recovery_module_has_no_forbidden_imports():
    assert _offenders(RECOVERY_PATH) == []
    assert _offenders(HISTORY_PATH) == []


def test_sweep_writes_only_loop_runs(db_session_factory):
    run = _timed_out_run()

    before_other = (
        len(decision_repository.search(limit=200)),
        len(action_repository.list_records("u-orphan")),
    )
    swept = recovery.sweep_orphan_runs()
    after_other = (
        len(decision_repository.search(limit=200)),
        len(action_repository.list_records("u-orphan")),
    )

    assert swept == [run.id]
    assert before_other == after_other
    row = loop_run_repository.get(run.id)
    assert row.status == "aborted"


def test_session_linkage_queryable(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="true")
    first = open_foreground_run("u-link", session_id="S-link")
    second = open_foreground_run("u-link", session_id="S-link")
    _action("act-1", run_id=first.run_id, user_id="u-link", session_id="S-link")
    _trace(db_session_factory, "tr-1", user_id="u-link", correlation_id=first.run_id)
    close_run(first, "done")
    close_run(second, "done")

    histories = execution_history.history_for_session("S-link")

    assert len(histories) == 2
    assert {h.run_id for h in histories} == {first.run_id, second.run_id}
    linked = next(h for h in histories if h.run_id == first.run_id)
    assert linked.traces
    assert linked.actions
