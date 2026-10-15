"""V8.5 relationship_snapshots 仓储：关键帧快照，限频保留，回滚锚点。"""

from datetime import datetime

from sqlalchemy import delete, select

from app.core import timeutil
from app.core import ids
from app.core.db import RelationshipSnapshotRow, SessionLocal
from app.core.settings import get_settings
from app.models.relationship import RelationshipSnapshot, RelationshipState
from app.core.constants import RELATIONSHIP_DIMENSIONS


def _to_snapshot(row: RelationshipSnapshotRow) -> RelationshipSnapshot:
    return RelationshipSnapshot(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        version=row.version,
        dimensions=dict(row.dimensions or {}),
        stage=row.stage,
        conflict_status=row.conflict_status,
        trigger=row.trigger,
        created_at=row.created_at,
    )


def _dimensions_from_state(state: RelationshipState) -> dict[str, float]:
    return {dim: getattr(state, dim, 0.0) for dim in RELATIONSHIP_DIMENSIONS}


def list_snapshots(user_id: str, limit: int = 50) -> list[RelationshipSnapshot]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(RelationshipSnapshotRow)
            .where(RelationshipSnapshotRow.user_id == user_id)
            .order_by(RelationshipSnapshotRow.version.desc())
            .limit(max(1, min(limit, 200)))
        ).all()
        return [_to_snapshot(row) for row in rows]


def get_latest_before(user_id: str, target_version: int) -> RelationshipSnapshot | None:
    with SessionLocal() as session:
        row = session.scalars(
            select(RelationshipSnapshotRow)
            .where(
                RelationshipSnapshotRow.user_id == user_id,
                RelationshipSnapshotRow.version <= target_version,
            )
            .order_by(RelationshipSnapshotRow.version.desc())
            .limit(1)
        ).first()
        return _to_snapshot(row) if row is not None else None


def create_snapshot(
    user_id: str,
    version: int,
    state: RelationshipState,
    trigger: str = "manual",
    now: datetime | None = None,
) -> RelationshipSnapshot:
    created_at = timeutil.ensure_aware(now) or timeutil.now()
    with SessionLocal() as session:
        row = RelationshipSnapshotRow(
            id=ids.new_id_str(),
            user_id=user_id,
            character_id="asuna",
            version=version,
            dimensions=_dimensions_from_state(state),
            stage=state.stage,
            conflict_status=getattr(state, "conflict_status", "none") or "none",
            trigger=trigger,
            created_at=created_at,
        )
        session.add(row)
        session.flush()
        keep = get_settings().rel_snapshot_keep
        rows = session.scalars(
            select(RelationshipSnapshotRow.id)
            .where(RelationshipSnapshotRow.user_id == user_id)
            .order_by(RelationshipSnapshotRow.version.desc())
            .offset(keep)
        ).all()
        if rows:
            session.execute(
                delete(RelationshipSnapshotRow).where(
                    RelationshipSnapshotRow.id.in_(rows)
                )
            )
        session.commit()
        session.refresh(row)
        return _to_snapshot(row)


def get_earliest_version(user_id: str) -> int | None:
    with SessionLocal() as session:
        row = session.scalars(
            select(RelationshipSnapshotRow.version)
            .where(RelationshipSnapshotRow.user_id == user_id)
            .order_by(RelationshipSnapshotRow.version.asc())
            .limit(1)
        ).first()
        return row if row is not None else None
