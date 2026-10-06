"""V7.8 保留策略统一清理：过期删除、未过期保留、四表串行。"""

from datetime import datetime, timedelta

from app.core import timeutil
from app.application import observability
from app.core.db import (
    DecisionRecordRow,
    LlmCallRecordRow,
    PromptSnapshotRow,
    RuntimeTraceRow,
)
from app.repositories import (
    decision_repository,
    llm_call_repository,
    prompt_snapshot_repository,
    trace_repository,
)


def _seed_old_and_fresh(db_session_factory):
    now = timeutil.now()
    old = now - timedelta(days=30)
    fresh = now
    with trace_repository.SessionLocal() as session:
        session.add(
            RuntimeTraceRow(
                id="old-trace", kind="turn", user_id="u1", status="complete",
                duration_ms=1.0, steps=[], events=[], token_usage={}, meta={},
                created_at=old,
            )
        )
        session.add(
            RuntimeTraceRow(
                id="fresh-trace", kind="turn", user_id="u1", status="complete",
                duration_ms=1.0, steps=[], events=[], token_usage={}, meta={},
                created_at=fresh,
            )
        )
        session.add(
            LlmCallRecordRow(
                id="old-call", call_site="answer", status="ok", latency_ms=1.0,
                created_at=old,
            )
        )
        session.add(
            LlmCallRecordRow(
                id="fresh-call", call_site="answer", status="ok", latency_ms=1.0,
                created_at=fresh,
            )
        )
        session.add(
            PromptSnapshotRow(
                id="old-snap", request_id="old-trace", call_site="answer",
                messages=[], truncated=False, created_at=old,
            )
        )
        session.add(
            PromptSnapshotRow(
                id="fresh-snap", request_id="fresh-trace", call_site="answer",
                messages=[], truncated=False, created_at=fresh,
            )
        )
        session.add(
            DecisionRecordRow(
                id="old-dec", kind="proactive_autonomy", user_id="u1",
                input_snapshot={}, decision="deny", reason="r", created_at=old,
            )
        )
        session.add(
            DecisionRecordRow(
                id="fresh-dec", kind="proactive_autonomy", user_id="u1",
                input_snapshot={}, decision="deny", reason="r", created_at=fresh,
            )
        )
        session.commit()


def _row_count(row_cls, repo_module):
    with repo_module.SessionLocal() as session:
        return session.query(row_cls).count()


def test_prune_all_keeps_fresh_and_removes_expired(db_session_factory, override_settings):
    _seed_old_and_fresh(db_session_factory)

    pruned = observability.prune_all()

    assert pruned == 4
    with trace_repository.SessionLocal() as session:
        remaining_traces = {row.id for row in session.query(RuntimeTraceRow).all()}
        remaining_calls = {row.id for row in session.query(LlmCallRecordRow).all()}
        remaining_snaps = {row.id for row in session.query(PromptSnapshotRow).all()}
        remaining_decs = {row.id for row in session.query(DecisionRecordRow).all()}
    assert remaining_traces == {"fresh-trace"}
    assert remaining_calls == {"fresh-call"}
    assert remaining_snaps == {"fresh-snap"}
    assert remaining_decs == {"fresh-dec"}


def test_retention_loop_body_is_safe_on_empty_db(db_session_factory):
    assert observability.prune_all() == 0
