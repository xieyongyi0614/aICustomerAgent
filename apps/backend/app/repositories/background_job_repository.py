"""background_jobs 通用仓储（MEM-004 起供 Memory 后台任务使用；MEM-009 扩展执行协议）。

幂等入队依赖 idempotency_key 唯一约束：重复入队返回 False，不报错。
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core.db import BackgroundJobRow, SessionLocal

logger = logging.getLogger(__name__)


def enqueue_job(
    job_type: str,
    payload: dict,
    idempotency_key: str,
    run_at: datetime | None = None,
    last_error: str | None = None,
) -> bool:
    now = datetime.now()
    with SessionLocal() as session:
        existing = (
            session.query(BackgroundJobRow)
            .filter(BackgroundJobRow.idempotency_key == idempotency_key)
            .first()
        )
        if existing is not None:
            return False
        session.add(
            BackgroundJobRow(
                id=str(uuid.uuid4()),
                job_type=job_type,
                payload=payload,
                status="pending",
                attempts=0,
                run_at=run_at or now,
                idempotency_key=idempotency_key,
                last_error=last_error,
                created_at=now,
            )
        )
        try:
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
            return False


def has_job(idempotency_key: str) -> bool:
    """幂等键是否已占用（入队前预检用，只读不写）。"""
    if not idempotency_key:
        return False
    with SessionLocal() as session:
        return (
            session.query(BackgroundJobRow.id)
            .filter(BackgroundJobRow.idempotency_key == idempotency_key)
            .first()
            is not None
        )


def complete_jobs(job_type: str, idempotency_keys: list[str]) -> int:
    if not idempotency_keys:
        return 0
    with SessionLocal() as session:
        rows = (
            session.query(BackgroundJobRow)
            .filter(
                BackgroundJobRow.job_type == job_type,
                BackgroundJobRow.status == "pending",
                BackgroundJobRow.idempotency_key.in_(idempotency_keys),
            )
            .all()
        )
        for row in rows:
            row.status = "done"
        session.commit()
        return len(rows)


def list_jobs(job_type: str, status: str | None = None, limit: int = 50):
    with SessionLocal() as session:
        query = session.query(BackgroundJobRow).filter(
            BackgroundJobRow.job_type == job_type
        )
        if status is not None:
            query = query.filter(BackgroundJobRow.status == status)
        rows = query.order_by(BackgroundJobRow.created_at.asc()).limit(limit).all()
        for row in rows:
            session.expunge(row)
        return list(rows)
