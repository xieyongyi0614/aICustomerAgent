"""agent_metric_snapshots 仓储（AGENT-006）：周期快照唯一写面（评估只读旁路的例外本体）。"""

from datetime import datetime

from app.core import timeutil
from app.core import ids
from app.core.db import AgentMetricSnapshotRow, SessionLocal


def get_window(user_id: str, window_start: datetime, character_id: str = "asuna") -> AgentMetricSnapshotRow | None:
    with SessionLocal() as session:
        return (
            session.query(AgentMetricSnapshotRow)
            .filter(
                AgentMetricSnapshotRow.user_id == user_id,
                AgentMetricSnapshotRow.character_id == character_id,
                AgentMetricSnapshotRow.window_start == window_start,
            )
            .first()
        )


def save(
    user_id: str,
    window_start: datetime,
    window_end: datetime,
    metrics: dict,
    trend: dict | None,
    character_id: str = "asuna",
    now: datetime | None = None,
) -> AgentMetricSnapshotRow:
    """按 (user, character, window_start) upsert：同窗口重复执行不落第二行。"""
    now = timeutil.ensure_aware(now) or timeutil.now()
    with SessionLocal() as session:
        row = (
            session.query(AgentMetricSnapshotRow)
            .filter(
                AgentMetricSnapshotRow.user_id == user_id,
                AgentMetricSnapshotRow.character_id == character_id,
                AgentMetricSnapshotRow.window_start == window_start,
            )
            .first()
        )
        if row is None:
            row = AgentMetricSnapshotRow(
                id=ids.new_id_str(),
                user_id=user_id,
                character_id=character_id,
                window_start=window_start,
                created_at=now,
            )
            session.add(row)
        row.window_end = window_end
        row.metrics = metrics
        row.trend = trend
        session.commit()
        return row


def list_recent(user_id: str, limit: int = 7, character_id: str = "asuna") -> list[AgentMetricSnapshotRow]:
    with SessionLocal() as session:
        return (
            session.query(AgentMetricSnapshotRow)
            .filter(
                AgentMetricSnapshotRow.user_id == user_id,
                AgentMetricSnapshotRow.character_id == character_id,
            )
            .order_by(AgentMetricSnapshotRow.window_start.desc())
            .limit(max(limit, 1))
            .all()
        )
