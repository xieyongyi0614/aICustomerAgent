"""V9 action_records 仓储（V9-004，M11）。沿用模块级函数仓储惯例。"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.db import ActionRecordRow, SessionLocal
from app.core.settings import get_settings
from app.models.action import ActionRecord

logger = logging.getLogger(__name__)


def new_record_id() -> str:
    return f"act_{uuid.uuid4().hex[:8]}"


def _to_record(row: ActionRecordRow) -> ActionRecord:
    return ActionRecord(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        session_id=row.session_id,
        source=row.source,
        action_type=row.action_type,
        intent=row.intent or {},
        goal_id=row.goal_id,
        target_record_id=row.target_record_id,
        dedupe_key=row.dedupe_key,
        params=row.params or {},
        status=row.status,
        gate_reason=row.gate_reason,
        steps=row.steps or [],
        result=row.result,
        attempt=row.attempt,
        next_retry_at=row.next_retry_at,
        scheduled_at=row.scheduled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        executed_at=row.executed_at,
    )


def save_record(record: ActionRecord) -> ActionRecord:
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(ActionRecordRow, record.id)
        if row is None:
            row = ActionRecordRow(
                id=record.id,
                user_id=record.user_id,
                character_id=record.character_id,
                session_id=record.session_id,
                source=record.source,
                action_type=record.action_type,
                intent=record.intent,
                goal_id=record.goal_id,
                target_record_id=record.target_record_id,
                dedupe_key=record.dedupe_key,
                params=record.params,
                status=record.status,
                gate_reason=record.gate_reason,
                steps=record.steps,
                result=record.result,
                attempt=record.attempt,
                next_retry_at=record.next_retry_at,
                scheduled_at=record.scheduled_at,
                created_at=record.created_at or now,
                updated_at=record.updated_at or now,
                executed_at=record.executed_at,
            )
            session.add(row)
        else:
            for field in (
                "status",
                "gate_reason",
                "steps",
                "result",
                "attempt",
                "next_retry_at",
                "scheduled_at",
                "params",
                "goal_id",
                "executed_at",
            ):
                setattr(row, field, getattr(record, field))
            row.updated_at = record.updated_at or now
        session.commit()
        return _to_record(row)


def get_record(record_id: str) -> ActionRecord | None:
    with SessionLocal() as session:
        row = session.get(ActionRecordRow, record_id)
        return _to_record(row) if row is not None else None


def list_records(user_id: str, status: str | None = None, limit: int = 50) -> list[ActionRecord]:
    stmt = select(ActionRecordRow).where(ActionRecordRow.user_id == user_id)
    if status is not None:
        stmt = stmt.where(ActionRecordRow.status == status)
    stmt = stmt.order_by(ActionRecordRow.created_at.desc()).limit(limit)
    with SessionLocal() as session:
        return [_to_record(row) for row in session.scalars(stmt)]


def list_by_status(status: str, limit: int = 100) -> list[ActionRecord]:
    stmt = (
        select(ActionRecordRow)
        .where(ActionRecordRow.status == status)
        .order_by(ActionRecordRow.created_at.desc())
        .limit(limit)
    )
    with SessionLocal() as session:
        return [_to_record(row) for row in session.scalars(stmt)]


def list_retryable(now: datetime, limit: int = 50) -> list[ActionRecord]:
    stmt = (
        select(ActionRecordRow)
        .where(ActionRecordRow.status == "executing")
        .where(ActionRecordRow.next_retry_at.is_not(None))
        .where(ActionRecordRow.next_retry_at <= now)
        .order_by(ActionRecordRow.next_retry_at)
        .limit(limit)
    )
    with SessionLocal() as session:
        return [_to_record(row) for row in session.scalars(stmt)]


def list_planned(now: datetime, limit: int = 50) -> list[ActionRecord]:
    stmt = (
        select(ActionRecordRow)
        .where(ActionRecordRow.status == "planned")
        .order_by(ActionRecordRow.created_at)
        .limit(limit)
    )
    with SessionLocal() as session:
        return [_to_record(row) for row in session.scalars(stmt)]


def list_by_dedupe(user_id: str, dedupe_key: str, since: datetime) -> list[ActionRecord]:
    stmt = (
        select(ActionRecordRow)
        .where(ActionRecordRow.user_id == user_id)
        .where(ActionRecordRow.dedupe_key == dedupe_key)
        .where(ActionRecordRow.created_at >= since)
        .order_by(ActionRecordRow.created_at.desc())
    )
    with SessionLocal() as session:
        return [_to_record(row) for row in session.scalars(stmt)]


def count_active(user_id: str) -> int:
    stmt = (
        select(ActionRecordRow)
        .where(ActionRecordRow.user_id == user_id)
        .where(ActionRecordRow.status.in_(["created", "planned", "executing"]))
    )
    with SessionLocal() as session:
        return len(list(session.scalars(stmt)))


def recent_records(user_id: str, limit: int = 20) -> list[ActionRecord]:
    return list_records(user_id, limit=limit)


def retain_cleanup() -> int:
    retention_days = get_settings().action_record_retention_days
    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    with SessionLocal() as session:
        for row in session.scalars(select(ActionRecordRow).where(ActionRecordRow.created_at < cutoff)):
            session.delete(row)
            removed += 1
        session.commit()
    if removed:
        logger.info("行动记录保留清理：删除 %d 条", removed)
    return removed
