"""V7.8 decision_records 仓储（decision-history.md §2）。

outcome 幂等补写（仅写空值）；retention 惰性清理在 save 路径顺带执行。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from app.core import ids
from app.core.db import DecisionRecordRow, SessionLocal
from app.core.settings import get_settings
from app.models.observability import DecisionKind, DecisionRecord

logger = logging.getLogger(__name__)


def _to_model(row: DecisionRecordRow) -> DecisionRecord:
    return DecisionRecord(
        id=row.id,
        kind=DecisionKind(row.kind),
        request_id=row.request_id,
        user_id=row.user_id,
        conversation_id=row.conversation_id,
        action_id=row.action_id,
        trigger=row.trigger,
        input_snapshot=row.input_snapshot or {},
        decision=row.decision,
        reason=row.reason or "",
        confidence=row.confidence,
        outcome=row.outcome,
        candidates=row.candidates,
        created_at=row.created_at,
    )


def _from_model(record: DecisionRecord, created_at: datetime) -> DecisionRecordRow:
    return DecisionRecordRow(
        id=record.id,
        kind=record.kind.value if hasattr(record.kind, "value") else str(record.kind),
        request_id=record.request_id,
        user_id=record.user_id,
        conversation_id=record.conversation_id,
        action_id=record.action_id,
        trigger=record.trigger,
        input_snapshot=record.input_snapshot,
        decision=record.decision,
        reason=record.reason,
        confidence=record.confidence,
        outcome=record.outcome,
        candidates=record.candidates,
        created_at=created_at,
    )


def save(record: DecisionRecord) -> None:
    now = datetime.now()
    try:
        with SessionLocal() as session:
            session.merge(_from_model(record, now))
            session.commit()
    except Exception:
        logger.exception("决策记录落库失败，已忽略")
        return
    prune_before(now - timedelta(days=get_settings().observability_decision_retention_days))


def mark_outcome(action_id: str, outcome: str) -> int:
    try:
        with SessionLocal() as session:
            updated = (
                session.query(DecisionRecordRow)
                .filter(
                    DecisionRecordRow.action_id == action_id,
                    DecisionRecordRow.outcome.is_(None),
                )
                .update({"outcome": outcome})
            )
            session.commit()
            return updated
    except Exception:
        logger.exception("决策 outcome 补写失败，已忽略")
        return 0


def get_by_action(action_id: str) -> list[DecisionRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(DecisionRecordRow)
            .filter(DecisionRecordRow.action_id == action_id)
            .order_by(DecisionRecordRow.created_at.asc())
            .all()
        )
        return [_to_model(row) for row in rows]


def search(
    user_id: str | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    action_id: str | None = None,
    request_id: str | None = None,
    limit: int = 50,
    until: datetime | None = None,
) -> list[DecisionRecord]:
    with SessionLocal() as session:
        query = session.query(DecisionRecordRow)
        if user_id is not None:
            query = query.filter(DecisionRecordRow.user_id == user_id)
        if kind is not None:
            query = query.filter(DecisionRecordRow.kind == kind)
        if since is not None:
            query = query.filter(DecisionRecordRow.created_at >= since)
        if until is not None:
            query = query.filter(DecisionRecordRow.created_at <= until)
        if action_id is not None:
            query = query.filter(DecisionRecordRow.action_id == action_id)
        if request_id is not None:
            query = query.filter(DecisionRecordRow.request_id == request_id)
        rows = (
            query.order_by(DecisionRecordRow.created_at.desc())
            .limit(max(1, min(limit, 200)))
            .all()
        )
        return [_to_model(row) for row in rows]


def list_rows_by_user_window(
    user_id: str,
    started_at: datetime,
    ended_at: datetime,
    limit: int = 200,
) -> list[DecisionRecordRow]:
    with SessionLocal() as session:
        return (
            session.query(DecisionRecordRow)
            .filter(
                DecisionRecordRow.user_id == user_id,
                DecisionRecordRow.created_at >= started_at,
                DecisionRecordRow.created_at <= ended_at,
            )
            .order_by(DecisionRecordRow.created_at.asc())
            .limit(limit)
            .all()
        )


def count_by_user(user_id: str) -> int:
    """该用户的决策记录条数（版本投影用）。

    与 `len(search(user_id=..., limit=1000))` 的区别（RT-ALL-code-review M-10）：
    后者受 `search` 的 `limit` 截断（上限 1000），条数一旦触顶版本号就不再增长——
    版本语义失真。本函数走 count 聚合，不受截断影响。
    """
    with SessionLocal() as session:
        total = (
            session.query(func.count(DecisionRecordRow.id))
            .filter(DecisionRecordRow.user_id == user_id)
            .scalar()
        )
        return int(total or 0)


def prune_before(cutoff: datetime) -> int:
    with SessionLocal() as session:
        deleted = (
            session.query(DecisionRecordRow)
            .filter(DecisionRecordRow.created_at < cutoff)
            .delete()
        )
        session.commit()
        return deleted


def new_decision_id() -> str:
    return ids.new_id_str()
