"""V7.8 runtime_traces 仓储（persistence.md §2）。

一次运行一行，id=request_id 幂等覆盖；retention 惰性清理在 save 路径顺带执行。
"""

import logging
from datetime import datetime, timedelta

from app.core import ids
from app.core.db import RuntimeTraceRow, SessionLocal
from app.core.settings import get_settings
from app.models.observability import RuntimeTrace, TraceEvent, TraceKind, TraceStep

logger = logging.getLogger(__name__)


def _to_model(row: RuntimeTraceRow) -> RuntimeTrace:
    return RuntimeTrace(
        trace_id=row.id,
        kind=TraceKind(row.kind),
        user_id=row.user_id,
        conversation_id=row.conversation_id,
        turn_id=row.turn_id,
        action_id=row.action_id,
        correlation_id=row.correlation_id,
        status=row.status,
        started_at=row.started_at,
        duration_ms=row.duration_ms or 0.0,
        steps=[TraceStep(**step) for step in (row.steps or [])],
        events=[TraceEvent(**event) for event in (row.events or [])],
        token_usage=row.token_usage or {},
        model_name=row.model_name,
        meta=row.meta or {},
    )


def _from_model(trace: RuntimeTrace, created_at: datetime) -> RuntimeTraceRow:
    return RuntimeTraceRow(
        id=trace.trace_id,
        kind=trace.kind.value if hasattr(trace.kind, "value") else str(trace.kind),
        user_id=trace.user_id,
        conversation_id=trace.conversation_id,
        turn_id=trace.turn_id,
        action_id=trace.action_id,
        correlation_id=trace.correlation_id,
        status=trace.status,
        started_at=trace.started_at,
        duration_ms=trace.duration_ms,
        steps=[step.model_dump() for step in trace.steps],
        events=[event.model_dump() for event in trace.events],
        token_usage=trace.token_usage,
        model_name=trace.model_name,
        meta=trace.meta,
        created_at=created_at,
    )


def save(trace: RuntimeTrace) -> None:
    now = datetime.now()
    try:
        with SessionLocal() as session:
            session.merge(_from_model(trace, now))
            session.commit()
    except Exception:
        logger.exception("runtime trace 落库失败，已忽略")
        return
    prune_before(now - timedelta(days=get_settings().observability_trace_retention_days))


def get_by_turn(turn_id: str) -> RuntimeTrace | None:
    with SessionLocal() as session:
        row = (
            session.query(RuntimeTraceRow)
            .filter(RuntimeTraceRow.turn_id == turn_id)
            .order_by(RuntimeTraceRow.created_at.desc())
            .first()
        )
        return _to_model(row) if row is not None else None


def get_by_trace_id(trace_id: str) -> RuntimeTrace | None:
    with SessionLocal() as session:
        row = session.get(RuntimeTraceRow, trace_id)
        return _to_model(row) if row is not None else None


def list_by_conversation(conversation_id: str, limit: int = 20) -> list[RuntimeTrace]:
    with SessionLocal() as session:
        rows = (
            session.query(RuntimeTraceRow)
            .filter(RuntimeTraceRow.conversation_id == conversation_id)
            .order_by(RuntimeTraceRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def list_by_correlation_id(correlation_id: str, limit: int = 200) -> list[RuntimeTraceRow]:
    with SessionLocal() as session:
        return (
            session.query(RuntimeTraceRow)
            .filter(RuntimeTraceRow.correlation_id == correlation_id)
            .order_by(RuntimeTraceRow.created_at.asc())
            .limit(limit)
            .all()
        )


def list_by_action_ids(action_ids: list[str], limit: int = 200) -> list[RuntimeTraceRow]:
    if not action_ids:
        return []
    with SessionLocal() as session:
        return (
            session.query(RuntimeTraceRow)
            .filter(RuntimeTraceRow.action_id.in_(action_ids))
            .order_by(RuntimeTraceRow.created_at.asc())
            .limit(limit)
            .all()
        )


def list_rows_by_user_window(
    user_id: str,
    started_at: datetime,
    ended_at: datetime,
    limit: int = 200,
) -> list[RuntimeTraceRow]:
    with SessionLocal() as session:
        return (
            session.query(RuntimeTraceRow)
            .filter(
                RuntimeTraceRow.user_id == user_id,
                RuntimeTraceRow.created_at >= started_at,
                RuntimeTraceRow.created_at <= ended_at,
            )
            .order_by(RuntimeTraceRow.created_at.asc())
            .limit(limit)
            .all()
        )


def list_since(cutoff: datetime, limit: int = 5000) -> list[RuntimeTrace]:
    with SessionLocal() as session:
        rows = (
            session.query(RuntimeTraceRow)
            .filter(RuntimeTraceRow.created_at >= cutoff)
            .order_by(RuntimeTraceRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def prune_before(cutoff: datetime) -> int:
    with SessionLocal() as session:
        deleted = (
            session.query(RuntimeTraceRow)
            .filter(RuntimeTraceRow.created_at < cutoff)
            .delete()
        )
        session.commit()
        return deleted


def new_trace_id() -> str:
    return ids.new_id_str()
