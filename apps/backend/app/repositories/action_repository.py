"""V9 action_records + V2.6.0 action_schedules 仓储（模块级函数仓储惯例）。"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import timeutil
from app.core import ids
from app.core.db import ActionRecordRow, ActionScheduleRow, OutboxEventRow, SessionLocal
from app.core.settings import get_settings
from app.models.action import ActionRecord, ActionSchedule

logger = logging.getLogger(__name__)


def new_record_id() -> str:
    return ids.new_id_str()


def new_schedule_id() -> str:
    return ids.new_id_str()


def _to_record(row: ActionRecordRow) -> ActionRecord:
    return ActionRecord(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        session_id=row.session_id,
        run_id=row.run_id,
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
        priority=row.priority,
        next_retry_at=row.next_retry_at,
        scheduled_at=row.scheduled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        executed_at=row.executed_at,
    )


def _to_schedule(row: ActionScheduleRow) -> ActionSchedule:
    return ActionSchedule(
        id=row.id,
        action_id=row.action_id,
        when_type=row.when_type,
        scheduled_at=row.scheduled_at,
        priority=row.priority,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _record_upsert(row: ActionRecordRow, record: ActionRecord, now: datetime) -> None:
    if row is None:
        return
    for field in (
        "status",
        "gate_reason",
        "steps",
        "result",
        "attempt",
        "priority",
        "next_retry_at",
        "scheduled_at",
        "params",
        "goal_id",
        "executed_at",
    ):
        setattr(row, field, getattr(record, field))
    row.updated_at = record.updated_at or now


def save_record(record: ActionRecord) -> ActionRecord:
    now = timeutil.now()
    with SessionLocal() as session:
        row = session.get(ActionRecordRow, record.id)
        if row is None:
            row = ActionRecordRow(
                id=record.id,
                user_id=record.user_id,
                character_id=record.character_id,
                session_id=record.session_id,
                run_id=record.run_id,
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
                priority=record.priority,
                next_retry_at=record.next_retry_at,
                scheduled_at=record.scheduled_at,
                created_at=record.created_at or now,
                updated_at=record.updated_at or now,
                executed_at=record.executed_at,
            )
            session.add(row)
        else:
            _record_upsert(row, record, now)
        session.commit()
        return _to_record(row)


def list_by_run_id(run_id: str, limit: int = 100) -> list[ActionRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(ActionRecordRow)
            .filter(ActionRecordRow.run_id == run_id)
            .order_by(ActionRecordRow.created_at.asc())
            .limit(limit)
            .all()
        )
        return [_to_record(row) for row in rows]


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


def list_stale_executing(updated_before: datetime, limit: int = 50) -> list[ActionRecord]:
    stmt = (
        select(ActionRecordRow)
        .where(ActionRecordRow.status == "executing")
        .where(ActionRecordRow.updated_at.is_not(None))
        .where(ActionRecordRow.updated_at <= updated_before)
        .order_by(ActionRecordRow.updated_at)
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
    cutoff = timeutil.now() - timedelta(days=retention_days)
    removed = 0
    with SessionLocal() as session:
        for row in session.scalars(select(ActionRecordRow).where(ActionRecordRow.created_at < cutoff)):
            session.delete(row)
            removed += 1
        session.commit()
    if removed:
        logger.info("行动记录保留清理：删除 %d 条", removed)
    return removed


def save_record_with_outbox(
    record: ActionRecord, outbox_payload: dict, idempotency_key: str
) -> ActionRecord:
    """行动终态迁移与 outbox 登记同事务落库（LIFE-004）。

    幂等键 = action_id；同键重放（IntegrityError）按已登记处理不报错。
    """
    now = timeutil.now()
    with SessionLocal() as session:
        row = session.get(ActionRecordRow, record.id)
        if row is None:
            row = ActionRecordRow(
                id=record.id,
                user_id=record.user_id,
                character_id=record.character_id,
                session_id=record.session_id,
                run_id=record.run_id,
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
                priority=record.priority,
                next_retry_at=record.next_retry_at,
                scheduled_at=record.scheduled_at,
                created_at=record.created_at or now,
                updated_at=record.updated_at or now,
                executed_at=record.executed_at,
            )
            session.add(row)
        else:
            _record_upsert(row, record, now)
        session.add(
            OutboxEventRow(
                id=ids.new_id_str(),
                event_type="action_result",
                payload=outbox_payload,
                idempotency_key=idempotency_key,
                status="pending",
                attempts=0,
                created_at=now,
                updated_at=now,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            return get_record(record.id)
        session.refresh(row)
        return _to_record(row)


def save_schedule(schedule: ActionSchedule) -> ActionSchedule:
    now = timeutil.now()
    with SessionLocal() as session:
        row = session.get(ActionScheduleRow, schedule.id)
        if row is None:
            row = ActionScheduleRow(
                id=schedule.id,
                action_id=schedule.action_id,
                when_type=schedule.when_type,
                scheduled_at=schedule.scheduled_at,
                priority=schedule.priority,
                status=schedule.status,
                created_at=schedule.created_at or now,
                updated_at=schedule.updated_at or now,
            )
            session.add(row)
        else:
            row.when_type = schedule.when_type
            row.scheduled_at = schedule.scheduled_at
            row.priority = schedule.priority
            row.status = schedule.status
            row.updated_at = schedule.updated_at or now
        session.commit()
        session.refresh(row)
        return _to_schedule(row)


def get_schedule(action_id: str) -> ActionSchedule | None:
    with SessionLocal() as session:
        row = session.scalars(
            select(ActionScheduleRow).where(ActionScheduleRow.action_id == action_id)
        ).first()
        return _to_schedule(row) if row is not None else None


def list_due_schedules(now: datetime, limit: int = 50) -> list[ActionSchedule]:
    stmt = (
        select(ActionScheduleRow)
        .where(ActionScheduleRow.status.in_(("scheduled", "due")))
        .where(ActionScheduleRow.scheduled_at <= now)
        .order_by(
            ActionScheduleRow.priority.desc(),
            ActionScheduleRow.scheduled_at,
            ActionScheduleRow.id,
        )
        .limit(limit)
    )
    with SessionLocal() as session:
        return [_to_schedule(row) for row in session.scalars(stmt)]


def mark_schedule_executed(action_id: str) -> ActionSchedule | None:
    return _mark_schedule_status(action_id, "executed")


def mark_schedule_cancelled(action_id: str) -> ActionSchedule | None:
    return _mark_schedule_status(action_id, "cancelled")


def claim_due_schedule(action_id: str, now: datetime | None = None) -> ActionSchedule | None:
    """CAS：scheduled/due → due（消费端原子认领）。非可认领态返回 None。"""
    now = timeutil.ensure_aware(now) or timeutil.now()
    with SessionLocal() as session:
        row = session.scalars(
            select(ActionScheduleRow).where(ActionScheduleRow.action_id == action_id)
        ).first()
        if row is None or row.status not in ("scheduled", "due"):
            return None
        row.status = "due"
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_schedule(row)


def _mark_schedule_status(action_id: str, status: str) -> ActionSchedule | None:
    now = timeutil.now()
    with SessionLocal() as session:
        row = session.scalars(
            select(ActionScheduleRow).where(ActionScheduleRow.action_id == action_id)
        ).first()
        if row is None:
            return None
        row.status = status
        row.updated_at = now
        session.commit()
        session.refresh(row)
        return _to_schedule(row)
