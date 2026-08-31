"""V8.5 relationship_conflicts 仓储：单活跃冲突历史。"""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.core.db import RelationshipConflictRow, SessionLocal
from app.models.relationship import ConflictRecord, ConflictStatus


def _to_record(row: RelationshipConflictRow) -> ConflictRecord:
    return ConflictRecord(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        status=row.status,
        trigger_event_id=row.trigger_event_id,
        started_at=row.started_at,
        last_negative_at=row.last_negative_at,
        recovery_started_at=row.recovery_started_at,
        resolved_at=row.resolved_at,
        resolution=row.resolution,
        created_at=row.created_at,
    )


def get_active_conflict(user_id: str) -> ConflictRecord | None:
    """单活跃：最新一条未 resolved 的行（resolved 行即历史）。"""
    with SessionLocal() as session:
        row = session.scalars(
            select(RelationshipConflictRow)
            .where(RelationshipConflictRow.user_id == user_id)
            .order_by(RelationshipConflictRow.started_at.desc())
            .limit(1)
        ).first()
        if row is None or row.status == "resolved":
            return None
        return _to_record(row)


def list_conflicts(user_id: str, limit: int = 50) -> list[ConflictRecord]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipConflictRow)
            .where(RelationshipConflictRow.user_id == user_id)
            .order_by(RelationshipConflictRow.started_at.desc())
            .limit(limit)
        ).all()
        return [_to_record(row) for row in rows]


def create_conflict(record: ConflictRecord) -> ConflictRecord:
    with SessionLocal() as session:
        row = RelationshipConflictRow(
            id=record.id,
            user_id=record.user_id,
            character_id=record.character_id,
            status=record.status,
            trigger_event_id=record.trigger_event_id,
            started_at=record.started_at,
            last_negative_at=record.last_negative_at,
            recovery_started_at=record.recovery_started_at,
            resolved_at=record.resolved_at,
            resolution=record.resolution,
            created_at=record.created_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_record(row)


def update_status(record: ConflictRecord) -> ConflictRecord:
    """冲突迁移（同 id 行原地更新）；closed 行保留历史。"""
    with SessionLocal() as session:
        row = session.get(RelationshipConflictRow, record.id)
        if row is None:
            return create_conflict(record)
        row.status = record.status
        row.trigger_event_id = record.trigger_event_id
        row.last_negative_at = record.last_negative_at
        row.recovery_started_at = record.recovery_started_at
        row.resolved_at = record.resolved_at
        row.resolution = record.resolution
        session.commit()
        session.refresh(row)
        return _to_record(row)


def resolved_recovery_count(user_id: str) -> int:
    """resolved(reconciled) 次数（R1 单冲突一次幂等参考）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipConflictRow).where(
                RelationshipConflictRow.user_id == user_id,
                RelationshipConflictRow.status == "resolved",
            )
        ).all()
        return len(rows)