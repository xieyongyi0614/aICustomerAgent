"""V8.5 relationship_milestones 仓储：一次性里程碑，unique 幂等。"""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.core.db import RelationshipMilestoneRow, SessionLocal
from app.models.relationship import MilestoneRecord, RelationshipDelta


def _to_record(row: RelationshipMilestoneRow) -> MilestoneRecord:
    return MilestoneRecord(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        milestone_key=row.milestone_key,
        period_key=row.period_key,
        title=row.title,
        applied_bonus=RelationshipDelta(**(row.applied_bonus or {})),
        unlocks=tuple(row.unlocks or ()),
        meta=dict(row.meta or {}),
        created_at=row.created_at,
    )


def list_milestones(user_id: str) -> list[MilestoneRecord]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipMilestoneRow)
            .where(RelationshipMilestoneRow.user_id == user_id)
            .order_by(RelationshipMilestoneRow.created_at.desc())
        ).all()
        return [_to_record(row) for row in rows]


def existing_keys(user_id: str) -> set[tuple[str, str]]:
    """已达成 (milestone_key, period_key) 集合（幂等检测用，一条 SQL 预载）。"""
    with SessionLocal() as session:
        rows = session.execute(
            select(
                RelationshipMilestoneRow.milestone_key,
                RelationshipMilestoneRow.period_key,
            ).where(RelationshipMilestoneRow.user_id == user_id)
        ).all()
        return {(row.milestone_key, row.period_key) for row in rows}


def has_unlock(user_id: str, unlock_key: str) -> bool:
    """解锁查询 = EXISTS(milestones WHERE unlocks contains key)（JSON 列内存过滤）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipMilestoneRow).where(
                RelationshipMilestoneRow.user_id == user_id
            )
        ).all()
        return any(unlock_key in (row.unlocks or []) for row in rows)


def list_unlocks(user_id: str) -> tuple[str, ...]:
    """聚合该用户所有里程碑解锁的 key 集合（去重有序）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipMilestoneRow).where(
                RelationshipMilestoneRow.user_id == user_id
            )
        ).all()
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        for key in row.unlocks or []:
            if key and key not in seen:
                seen.add(key)
                result.append(key)
    return tuple(result)


def create_milestone(
    user_id: str,
    milestone_key: str,
    title: str,
    period_key: str = "",
    applied_bonus: RelationshipDelta | None = None,
    unlocks: tuple[str, ...] = (),
    meta: dict | None = None,
    now: datetime | None = None,
) -> MilestoneRecord | None:
    """写入里程碑；unique 冲突（重复检测）返回 None，不抛。"""
    with SessionLocal() as session:
        exists = session.scalars(
            select(RelationshipMilestoneRow.id).where(
                RelationshipMilestoneRow.user_id == user_id,
                RelationshipMilestoneRow.milestone_key == milestone_key,
                RelationshipMilestoneRow.period_key == period_key,
            )
        ).first()
        if exists is not None:
            return None
        row = RelationshipMilestoneRow(
            id=str(uuid.uuid4()),
            user_id=user_id,
            character_id="asuna",
            milestone_key=milestone_key,
            period_key=period_key,
            title=title,
            applied_bonus=(applied_bonus or RelationshipDelta()).model_dump(),
            unlocks=list(unlocks),
            meta=meta,
            created_at=now or datetime.now(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_record(row)


def count_keys_since(user_id: str, key_prefix: str, since: datetime) -> int:
    """指定前缀的里程碑自 since 起的计数（叙事里程碑频控用）。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipMilestoneRow).where(
                RelationshipMilestoneRow.user_id == user_id,
                RelationshipMilestoneRow.created_at >= since,
            )
        ).all()
        return sum(
            1 for row in rows if (row.milestone_key or "").startswith(key_prefix)
        )