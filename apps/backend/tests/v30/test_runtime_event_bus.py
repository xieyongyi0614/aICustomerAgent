"""RT-005 Runtime Event System 测试：派发 / 门控 / 隔离 / Trace / 边界。"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest

from app.application.agent_runtime import events
from app.application.agent_runtime.contracts import (
    EVENT_RUN_CLOSED,
    EVENT_RUN_OPENED,
    EVENT_STAGE_COMPLETED,
)
from app.services.observability.collector import TurnTraceSession

EVENTS_PATH = Path(events.__file__)
FORBIDDEN_IMPORTS = (
    "app.repositories",
    "app.application.outbox_consumer",
    "app.application.world_engine",
    "app.chains",
    "app.prompts",
)
FORBIDDEN_WRITE_TOKENS = ("session.add", ".commit(", "INSERT ", "UPDATE ", "DELETE ")


@pytest.fixture(autouse=True)
def _clean_bus():
    events.clear_subscribers()
    yield
    events.clear_subscribers()


def _event(event_type: str = EVENT_RUN_OPENED, run_id: str = "r1", correlation_id=None):
    return events.RuntimeEvent(
        event_type=event_type,
        run_id=run_id,
        session_id="s1",
        occurred_at=datetime.now(),
        correlation_id=correlation_id,
    )


def test_flag_off_returns_zero_and_no_side_effects(override_settings):
    override_settings(runtime_event_bus_enabled="false")
    seen: list = []
    events.subscribe(EVENT_RUN_OPENED, seen.append)
    trace = TurnTraceSession()

    assert events.emit(_event(), trace) == 0
    assert seen == []
    assert trace.steps == []


def test_emit_fans_out_in_registration_order(override_settings):
    override_settings(runtime_event_bus_enabled="true")
    order: list[str] = []
    events.subscribe(EVENT_RUN_OPENED, lambda event: order.append("a"))
    events.subscribe(EVENT_RUN_OPENED, lambda event: order.append("b"))
    events.subscribe(EVENT_RUN_OPENED, lambda event: order.append("c"))

    assert events.emit(_event()) == 3
    assert order == ["a", "b", "c"]


def test_emit_does_not_raise_when_handler_fails(override_settings):
    override_settings(runtime_event_bus_enabled="true")
    called: list = []

    def _boom(event):
        raise ValueError("bad")

    events.subscribe(EVENT_RUN_OPENED, _boom)
    events.subscribe(EVENT_RUN_OPENED, called.append)

    assert events.emit(_event()) == 1
    assert len(called) == 1


def test_handler_failure_recorded_in_trace(override_settings):
    override_settings(runtime_event_bus_enabled="true")

    def _boom(event):
        raise ValueError("bad")

    events.subscribe(EVENT_RUN_OPENED, _boom)
    trace = TurnTraceSession()

    events.emit(_event(run_id="r9"), trace)

    error_steps = [step for step in trace.steps if step.status == "error"]
    assert error_steps
    assert error_steps[-1].extra["run_id"] == "r9"
    assert error_steps[-1].extra["event_type"] == EVENT_RUN_OPENED


def test_subscribe_is_idempotent():
    handler = lambda event: None

    events.subscribe(EVENT_RUN_OPENED, handler)
    events.subscribe(EVENT_RUN_OPENED, handler)

    assert events.handler_count(EVENT_RUN_OPENED) == 1


def test_subscribe_rejects_unknown_event_type():
    with pytest.raises(ValueError):
        events.subscribe("Nope", lambda event: None)


def test_unsubscribe_removes_handler():
    handler = lambda event: None
    events.subscribe(EVENT_RUN_OPENED, handler)

    assert events.unsubscribe(EVENT_RUN_OPENED, handler) is True
    assert events.handler_count(EVENT_RUN_OPENED) == 0
    assert events.unsubscribe(EVENT_RUN_OPENED, handler) is False


def test_subscribers_returns_immutable_snapshot():
    handler = lambda event: None
    events.subscribe(EVENT_RUN_OPENED, handler)

    snapshot = events.subscribers(EVENT_RUN_OPENED)

    assert isinstance(snapshot, tuple)
    assert snapshot == (handler,)


def test_trace_records_event_with_correlation_id(override_settings):
    override_settings(runtime_event_bus_enabled="true")
    trace = TurnTraceSession()

    events.emit(_event(correlation_id="corr-1"), trace)

    extra = trace.steps[-1].extra
    assert extra["event_type"] == EVENT_RUN_OPENED
    assert extra["run_id"] == "r1"
    assert extra["correlation_id"] == "corr-1"


def test_constructors_build_expected_events(override_settings):
    override_settings(runtime_event_bus_enabled="true")
    captured: list = []
    events.subscribe(EVENT_RUN_OPENED, captured.append)
    events.subscribe(EVENT_STAGE_COMPLETED, captured.append)
    events.subscribe(EVENT_RUN_CLOSED, captured.append)

    events.emit_run_opened("r1", "s1")
    events.emit_stage_completed("r1", "s1", "observe", duration_ms=1.5)
    events.emit_run_closed("r1", "s1", "done")

    assert [event.event_type for event in captured] == [
        EVENT_RUN_OPENED,
        EVENT_STAGE_COMPLETED,
        EVENT_RUN_CLOSED,
    ]
    stage = next(event for event in captured if event.event_type == EVENT_STAGE_COMPLETED)
    assert stage.payload["stage"] == "observe"
    assert stage.payload["duration_ms"] == 1.5
    assert stage.payload["status"] == "ok"
    closed = next(event for event in captured if event.event_type == EVENT_RUN_CLOSED)
    assert closed.payload["status"] == "done"


def test_events_module_has_no_forbidden_imports():
    tree = ast.parse(EVENTS_PATH.read_text(encoding="utf-8"))
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


def test_events_module_performs_no_db_writes():
    source = EVENTS_PATH.read_text(encoding="utf-8")
    assert not any(token in source for token in FORBIDDEN_WRITE_TOKENS)


def test_bus_does_not_write_any_table(db_session_factory, override_settings):
    override_settings(runtime_event_bus_enabled="true")
    from app.core.db import Base

    def _counts():
        with db_session_factory() as session:
            return {
                table.name: session.query(table).count()
                for table in Base.metadata.sorted_tables
            }

    before = _counts()
    events.emit_run_opened("r-w", "s-w")
    events.emit_stage_completed("r-w", "s-w", "observe", duration_ms=0.5)
    events.emit_run_closed("r-w", "s-w", "done")

    assert _counts() == before
