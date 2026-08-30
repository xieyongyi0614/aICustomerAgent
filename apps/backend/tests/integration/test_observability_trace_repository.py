from datetime import datetime, timedelta

from app.models.observability import RuntimeTrace, TraceEvent, TraceKind, TraceStep
from app.repositories import trace_repository


def make_trace(
    trace_id="req-1",
    turn_id="101",
    conversation_id="conv-1",
) -> RuntimeTrace:
    return RuntimeTrace(
        trace_id=trace_id,
        kind=TraceKind.TURN,
        user_id="default-user",
        conversation_id=conversation_id,
        turn_id=turn_id,
        status="complete",
        duration_ms=12.5,
        steps=[
            TraceStep(name="llm", status="ok", duration_ms=10.0, first_token_ms=1.2),
            TraceStep(
                name="state_update",
                status="ok",
                duration_ms=2.5,
                extra={"mood": "happy"},
            ),
        ],
        events=[
            TraceEvent(kind="emotion_change", payload={"before": "calm", "after": "happy"})
        ],
        token_usage={"input_tokens": 17, "output_tokens": 8},
        model_name="fake",
        meta={"behavior": {"strategy": "care_action"}},
    )


def test_save_and_get_roundtrip(db_session_factory):
    trace_repository.save(make_trace())
    loaded = trace_repository.get_by_turn("101")
    assert loaded is not None
    assert loaded.trace_id == "req-1"
    assert loaded.kind is TraceKind.TURN
    assert loaded.user_id == "default-user"
    assert [step.name for step in loaded.steps] == ["llm", "state_update"]
    assert loaded.steps[0].first_token_ms == 1.2
    assert loaded.steps[1].extra == {"mood": "happy"}
    assert loaded.events[0].payload == {"before": "calm", "after": "happy"}
    assert loaded.token_usage == {"input_tokens": 17, "output_tokens": 8}
    assert loaded.meta == {"behavior": {"strategy": "care_action"}}
    by_id = trace_repository.get_by_trace_id("req-1")
    assert by_id is not None and by_id.trace_id == "req-1"


def test_get_by_turn_returns_latest_row(db_session_factory):
    trace_repository.save(make_trace(trace_id="req-a"))
    trace_repository.save(make_trace(trace_id="req-b"))
    loaded = trace_repository.get_by_turn("101")
    assert loaded is not None
    assert loaded.trace_id in ("req-a", "req-b")
    assert trace_repository.get_by_trace_id("req-a") is not None
    assert trace_repository.get_by_trace_id("req-b") is not None


def test_get_by_turn_missing_returns_none(db_session_factory):
    assert trace_repository.get_by_turn("no-such") is None
    assert trace_repository.get_by_trace_id("no-such") is None


def test_list_by_conversation_orders_recent_first(db_session_factory):
    trace_repository.save(make_trace(trace_id="req-1", turn_id="1"))
    trace_repository.save(make_trace(trace_id="req-2", turn_id="2"))
    rows = trace_repository.list_by_conversation("conv-1")
    assert len(rows) == 2
    assert {row.trace_id for row in rows} == {"req-1", "req-2"}
    assert trace_repository.list_by_conversation("other") == []


def test_prune_before_removes_only_expired(db_session_factory):
    trace_repository.save(make_trace(trace_id="req-old"))
    assert trace_repository.get_by_trace_id("req-old") is not None
    assert trace_repository.prune_before(datetime.now() + timedelta(days=1)) >= 1
    assert trace_repository.get_by_trace_id("req-old") is None
