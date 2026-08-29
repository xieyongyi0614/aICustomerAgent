import uuid
from datetime import datetime

from app.core.db import GoalRow, SessionLocal
from app.models.goal import GoalRecord, GoalSeed

_TERMINAL_STATUS = ("completed", "expired", "cancelled")


def _to_record(row: GoalRow) -> GoalRecord:
    return GoalRecord(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        type=row.type,
        description=row.description,
        priority=row.priority,
        status=row.status,
        horizon=row.horizon,
        source=row.source,
        created_turn=row.created_turn,
        expires_at_turn=row.expires_at_turn,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_row(record: GoalRecord) -> GoalRow:
    return GoalRow(
        id=record.id,
        user_id=record.user_id,
        character_id=record.character_id,
        type=record.type,
        description=record.description,
        priority=record.priority,
        status=record.status,
        horizon=record.horizon,
        source=record.source,
        created_turn=record.created_turn,
        expires_at_turn=record.expires_at_turn,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def seed_goals(
    user_id: str, seeds: list[GoalSeed], character_id: str = "asuna"
) -> int:
    now = datetime.now()
    with SessionLocal() as session:
        existing = (
            session.query(GoalRow)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.character_id == character_id,
                GoalRow.status == "active",
                GoalRow.horizon == "persistent",
            )
            .all()
        )
        existing_keys = {(row.type, row.description) for row in existing}
        created = 0
        for seed in seeds:
            if (seed.type, seed.description) in existing_keys:
                continue
            session.add(
                GoalRow(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    character_id=character_id,
                    type=seed.type,
                    description=seed.description,
                    priority=seed.priority,
                    status="active",
                    horizon="persistent",
                    source="definition",
                    created_turn=0,
                    expires_at_turn=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            created += 1
        session.commit()
        return created


def list_active(user_id: str, character_id: str = "asuna") -> list[GoalRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(GoalRow)
            .filter(
                GoalRow.user_id == user_id,
                GoalRow.character_id == character_id,
                GoalRow.status == "active",
            )
            .order_by(GoalRow.created_at.asc(), GoalRow.id.asc())
            .all()
        )
        return [_to_record(row) for row in rows]


def get_goal(goal_id: str) -> GoalRecord | None:
    with SessionLocal() as session:
        row = session.get(GoalRow, goal_id)
        return _to_record(row) if row is not None else None


def create_goal(record: GoalRecord) -> GoalRecord:
    with SessionLocal() as session:
        row = _to_row(record)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_record(row)


def finish_goal(goal_id: str, status: str) -> GoalRecord | None:
    if status not in _TERMINAL_STATUS:
        raise ValueError(f"非法终态：{status}")
    with SessionLocal() as session:
        row = session.get(GoalRow, goal_id)
        if row is None or row.status != "active":
            return _to_record(row) if row is not None else None
        row.status = status
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        return _to_record(row)


def complete_goal(goal_id: str) -> GoalRecord | None:
    return finish_goal(goal_id, "completed")


def expire_goal(goal_id: str) -> GoalRecord | None:
    return finish_goal(goal_id, "expired")


def cancel_goal(goal_id: str) -> GoalRecord | None:
    return finish_goal(goal_id, "cancelled")
