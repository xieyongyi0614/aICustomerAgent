from datetime import datetime, timedelta

from app.core import timeutil
from app.models.observability import DecisionKind, DecisionRecord
from app.repositories import decision_repository


def make_record(
    record_id="dec-1",
    action_id=None,
    decision="deny",
    kind=DecisionKind.PROACTIVE_AUTONOMY,
) -> DecisionRecord:
    return DecisionRecord(
        id=record_id,
        kind=kind,
        user_id="default-user",
        conversation_id="s1",
        action_id=action_id,
        trigger="conversation_inactivity",
        input_snapshot={"intimacy": 0.4, "attempt_count": 0},
        decision=decision,
        reason="静音时段",
    )


def test_save_and_search_roundtrip(db_session_factory):
    decision_repository.save(make_record())
    rows = decision_repository.search(user_id="default-user")
    assert len(rows) == 1
    record = rows[0]
    assert record.kind is DecisionKind.PROACTIVE_AUTONOMY
    assert record.decision == "deny"
    assert record.trigger == "conversation_inactivity"
    assert record.input_snapshot == {"intimacy": 0.4, "attempt_count": 0}
    assert record.outcome is None


def test_mark_outcome_idempotent_only_fills_null(db_session_factory):
    decision_repository.save(make_record(record_id="dec-a", action_id="act-1"))
    assert decision_repository.mark_outcome("act-1", "delivered") == 1
    assert decision_repository.mark_outcome("act-1", "acked") == 0
    record = decision_repository.get_by_action("act-1")[0]
    assert record.outcome == "delivered"
    assert decision_repository.mark_outcome("missing", "failed") == 0


def test_search_filters(db_session_factory):
    decision_repository.save(make_record(record_id="d1"))
    decision_repository.save(
        make_record(
            record_id="d2",
            action_id="act-2",
            decision="act",
        )
    )
    assert len(decision_repository.search(kind="proactive_autonomy")) == 2
    assert len(decision_repository.search(action_id="act-2")) == 1
    assert decision_repository.search(action_id="act-2")[0].decision == "act"
    assert len(decision_repository.search(since=timeutil.now() + timedelta(hours=1))) == 0
    assert len(decision_repository.search(user_id="nobody")) == 0


def test_prune_before(db_session_factory):
    decision_repository.save(make_record(record_id="dec-old"))
    assert decision_repository.prune_before(timeutil.now() + timedelta(days=1)) >= 1
    assert decision_repository.search(user_id="default-user") == []
