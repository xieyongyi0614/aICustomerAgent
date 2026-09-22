"""agent_state_snapshots 仓储（AGENT-002）：时点存档 + 保留期清理。投影存档，非真相源。"""

import uuid
from datetime import datetime, timedelta

from app.core.db import AgentStateSnapshotRow, SessionLocal


def get_by_run_id(run_id: str) -> AgentStateSnapshotRow | None:
    with SessionLocal() as session:
        return (
            session.query(AgentStateSnapshotRow)
            .filter(AgentStateSnapshotRow.run_id == run_id)
            .order_by(AgentStateSnapshotRow.created_at.desc())
            .first()
        )


def latest(user_id: str, character_id: str = "asuna") -> AgentStateSnapshotRow | None:
    with SessionLocal() as session:
        return (
            session.query(AgentStateSnapshotRow)
            .filter(
                AgentStateSnapshotRow.user_id == user_id,
                AgentStateSnapshotRow.character_id == character_id,
            )
            .order_by(AgentStateSnapshotRow.created_at.desc())
            .first()
        )


def list_recent(
    user_id: str, limit: int = 10, character_id: str = "asuna"
) -> list[AgentStateSnapshotRow]:
    with SessionLocal() as session:
        return (
            session.query(AgentStateSnapshotRow)
            .filter(
                AgentStateSnapshotRow.user_id == user_id,
                AgentStateSnapshotRow.character_id == character_id,
            )
            .order_by(AgentStateSnapshotRow.created_at.desc())
            .limit(limit)
            .all()
        )


def save(
    user_id: str,
    snapshot: dict,
    version: int,
    run_id: str | None = None,
    character_id: str = "asuna",
    now: datetime | None = None,
) -> AgentStateSnapshotRow:
    now = now or datetime.now()
    row = AgentStateSnapshotRow(
        id=str(uuid.uuid4()),
        run_id=run_id,
        user_id=user_id,
        character_id=character_id,
        snapshot=snapshot,
        version=version,
        created_at=now,
    )
    with SessionLocal() as session:
        session.add(row)
        session.commit()
    return row


def cleanup_expired(retention_days: int, now: datetime | None = None) -> int:
    cutoff = (now or datetime.now()) - timedelta(days=max(retention_days, 0))
    with SessionLocal() as session:
        deleted = (
            session.query(AgentStateSnapshotRow)
            .filter(AgentStateSnapshotRow.created_at < cutoff)
            .delete()
        )
        session.commit()
    return deleted
