"""development_changes 只读面（RT-003）：按用户聚合成长变更版本证据。

表本身无 `user_id`（归属 `development_state`），故经 `development_state_id` 关联过滤；
仅提供只读聚合，写入仍归 Development 域既有通道。
"""

from datetime import datetime

from app.core.db import DevelopmentChangeRow, DevelopmentStateRow, SessionLocal


def list_changes(
    user_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 200,
) -> list[DevelopmentChangeRow]:
    with SessionLocal() as session:
        query = (
            session.query(DevelopmentChangeRow)
            .join(
                DevelopmentStateRow,
                DevelopmentChangeRow.development_state_id == DevelopmentStateRow.id,
            )
            .filter(DevelopmentStateRow.user_id == user_id)
        )
        if since is not None:
            query = query.filter(DevelopmentChangeRow.created_at >= since)
        if until is not None:
            query = query.filter(DevelopmentChangeRow.created_at <= until)
        return query.order_by(DevelopmentChangeRow.created_at.asc()).limit(limit).all()


def count_changes(user_id: str) -> int:
    with SessionLocal() as session:
        return (
            session.query(DevelopmentChangeRow)
            .join(
                DevelopmentStateRow,
                DevelopmentChangeRow.development_state_id == DevelopmentStateRow.id,
            )
            .filter(DevelopmentStateRow.user_id == user_id)
            .count()
        )


def latest_change(user_id: str) -> datetime | None:
    with SessionLocal() as session:
        row = (
            session.query(DevelopmentChangeRow.created_at)
            .join(
                DevelopmentStateRow,
                DevelopmentChangeRow.development_state_id == DevelopmentStateRow.id,
            )
            .filter(DevelopmentStateRow.user_id == user_id)
            .order_by(DevelopmentChangeRow.created_at.desc())
            .first()
        )
        return row[0] if row is not None else None
