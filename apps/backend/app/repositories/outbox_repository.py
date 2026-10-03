"""outbox_events 仓储（LIFE-004）。

状态机 pending→consumed|failed；幂等键 = action_id 唯一；消费进度
（applied_ops / relationship_done）记录在 payload 内，崩溃重放按进度续走；
失败指数退避 max5 → failed 死信。时间基准用调用方注入 now。
"""

import logging
from datetime import datetime, timedelta

from app.core import ids
from app.core.db import OutboxEventRow, SessionLocal

logger = logging.getLogger(__name__)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now()


def get(idempotency_key: str) -> OutboxEventRow | None:
    with SessionLocal() as session:
        return (
            session.query(OutboxEventRow)
            .filter(OutboxEventRow.idempotency_key == idempotency_key)
            .first()
        )


def list_recent(status: str | None = None, limit: int = 50) -> list[OutboxEventRow]:
    with SessionLocal() as session:
        query = session.query(OutboxEventRow)
        if status is not None:
            query = query.filter(OutboxEventRow.status == status)
        return (
            query.order_by(OutboxEventRow.created_at.desc()).limit(limit).all()
        )


def list_pending(now: datetime | None = None, limit: int = 50) -> list[OutboxEventRow]:
    """到期待消费行（pending 且 next_retry_at≤now，FIFO）。"""
    now = _now(now)
    with SessionLocal() as session:
        return (
            session.query(OutboxEventRow)
            .filter(
                OutboxEventRow.status == "pending",
                (OutboxEventRow.next_retry_at.is_(None))
                | (OutboxEventRow.next_retry_at <= now),
            )
            .order_by(OutboxEventRow.created_at)
            .limit(limit)
            .all()
        )


def insert(payload: dict, idempotency_key: str, now: datetime | None = None) -> bool:
    """独立入队（测试/重放用；生产主路径走同事务 save_record_with_outbox）。"""
    now = _now(now)
    with SessionLocal() as session:
        existing = (
            session.query(OutboxEventRow)
            .filter(OutboxEventRow.idempotency_key == idempotency_key)
            .first()
        )
        if existing is not None:
            return False
        session.add(
            OutboxEventRow(
                id=ids.new_id_str(),
                event_type="action_result",
                payload=payload,
                idempotency_key=idempotency_key,
                status="pending",
                attempts=0,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        return True


def mark_consumed(idempotency_key: str, now: datetime | None = None) -> bool:
    """pending→consumed CAS（并发/重放双消费守卫）。"""
    now = _now(now)
    with SessionLocal() as session:
        updated = (
            session.query(OutboxEventRow)
            .filter(
                OutboxEventRow.idempotency_key == idempotency_key,
                OutboxEventRow.status == "pending",
            )
            .update({"status": "consumed", "updated_at": now})
        )
        session.commit()
        return bool(updated)


def advance_progress(idempotency_key: str, applied_ops: int, now: datetime | None = None) -> None:
    """推进 payload.applied_ops（每个 world op 落库后立即持久化，崩溃重放续走）。"""
    now = _now(now)
    with SessionLocal() as session:
        row = (
            session.query(OutboxEventRow)
            .filter(OutboxEventRow.idempotency_key == idempotency_key)
            .first()
        )
        if row is None:
            return
        row.payload = {**(row.payload or {}), "applied_ops": applied_ops}
        row.updated_at = now
        session.commit()


def mark_relationship_done(idempotency_key: str, now: datetime | None = None) -> None:
    now = _now(now)
    with SessionLocal() as session:
        row = (
            session.query(OutboxEventRow)
            .filter(OutboxEventRow.idempotency_key == idempotency_key)
            .first()
        )
        if row is None:
            return
        row.payload = {**(row.payload or {}), "relationship_done": True}
        row.updated_at = now
        session.commit()


def fail_for_retry(
    idempotency_key: str,
    reason: str,
    now: datetime | None = None,
    max_attempts: int = 5,
    backoff_seconds: int = 30,
) -> str:
    """失败重试调度：pending→pending(attempts+1+指数退避) 或 failed 死信。

    返回迁移后状态：pending / failed / unchanged。
    """
    now = _now(now)
    with SessionLocal() as session:
        row = (
            session.query(OutboxEventRow)
            .filter(OutboxEventRow.idempotency_key == idempotency_key)
            .with_for_update()
            .first()
        )
        if row is None or row.status != "pending":
            return "unchanged"
        attempts = row.attempts + 1
        row.attempts = attempts
        row.last_error = reason[:500]
        row.updated_at = now
        if attempts >= max_attempts:
            row.status = "failed"
        else:
            row.next_retry_at = now + timedelta(
                seconds=backoff_seconds * (2 ** (attempts - 1))
            )
        session.commit()
        return row.status


def requeue(idempotency_key: str, now: datetime | None = None) -> bool:
    """failed 死信手工重置 pending（ops 决策；重放按幂等键/进度标记防重）。"""
    now = _now(now)
    with SessionLocal() as session:
        updated = (
            session.query(OutboxEventRow)
            .filter(
                OutboxEventRow.idempotency_key == idempotency_key,
                OutboxEventRow.status == "failed",
            )
            .update({"status": "pending", "next_retry_at": None, "updated_at": now})
        )
        session.commit()
        return bool(updated)
