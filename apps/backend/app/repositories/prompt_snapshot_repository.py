"""V7.8 prompt_snapshots 仓储（persistence.md §2）。

调试数据，短 TTL；retention 惰性清理在 save 路径顺带执行。
"""

import logging
from datetime import datetime, timedelta

from app.core import timeutil
from app.core.db import PromptSnapshotRow, SessionLocal
from app.core.settings import get_settings
from app.models.observability import CallSite, PromptSnapshot

logger = logging.getLogger(__name__)


def _to_model(row: PromptSnapshotRow) -> PromptSnapshot:
    return PromptSnapshot(
        id=row.id,
        request_id=row.request_id,
        turn_id=row.turn_id,
        call_site=CallSite(row.call_site),
        profile_id=row.profile_id,
        model=row.model,
        messages=row.messages or [],
        section_budget=row.section_budget,
        truncated=bool(row.truncated),
        created_at=row.created_at,
    )


def _from_model(snapshot: PromptSnapshot, created_at: datetime) -> PromptSnapshotRow:
    return PromptSnapshotRow(
        id=snapshot.id,
        request_id=snapshot.request_id,
        turn_id=snapshot.turn_id,
        call_site=snapshot.call_site.value if hasattr(snapshot.call_site, "value") else str(snapshot.call_site),
        profile_id=snapshot.profile_id,
        model=snapshot.model,
        messages=snapshot.messages,
        section_budget=snapshot.section_budget,
        truncated=snapshot.truncated,
        created_at=created_at,
    )


def save(snapshot: PromptSnapshot) -> None:
    now = timeutil.now()
    try:
        with SessionLocal() as session:
            session.merge(_from_model(snapshot, now))
            session.commit()
    except Exception:
        logger.exception("prompt 快照落库失败，已忽略")
        return
    prune_before(now - timedelta(days=get_settings().observability_prompt_retention_days))


def get_by_turn(turn_id: str, limit: int = 50) -> list[PromptSnapshot]:
    with SessionLocal() as session:
        rows = (
            session.query(PromptSnapshotRow)
            .filter(PromptSnapshotRow.turn_id == turn_id)
            .order_by(PromptSnapshotRow.created_at.asc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def get_by_id(snapshot_id: str) -> PromptSnapshot | None:
    with SessionLocal() as session:
        row = session.get(PromptSnapshotRow, snapshot_id)
        return _to_model(row) if row is not None else None


def list_since(cutoff: datetime, limit: int = 5000) -> list[PromptSnapshot]:
    with SessionLocal() as session:
        rows = (
            session.query(PromptSnapshotRow)
            .filter(PromptSnapshotRow.created_at >= cutoff)
            .order_by(PromptSnapshotRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def prune_before(cutoff: datetime) -> int:
    with SessionLocal() as session:
        deleted = (
            session.query(PromptSnapshotRow)
            .filter(PromptSnapshotRow.created_at < cutoff)
            .delete()
        )
        session.commit()
        return deleted
