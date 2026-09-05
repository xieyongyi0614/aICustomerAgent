"""Insight 生命周期（REF-001）。

状态机 active→superseded|invalidated（两终态互斥、不复活、非法转换拒绝），
与 memory2 状态机同构但独立实现（Reflection 只写本域三表，不 import memory2）。
迁移 API 全部单事务：条件 UPDATE 带 status='active'，影响 0 行即 no-op，天然幂等。
invalidated_reason 必填由服务层前置校验 + DB CHECK 兜底；supersede 要求新行存在
且 active，不产生悬挂引用。原行不删除（审计保留）。
"""

import logging
import time
from datetime import datetime

from app.core.db import InsightRow, SessionLocal
from app.core.settings import get_settings
from app.models.reflection import Insight

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_lifecycle"

STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_INVALIDATED = "invalidated"

EVENT_SUPERSEDE = "supersede"
EVENT_INVALIDATE = "invalidate"

TRANSITIONS = {
    (STATUS_ACTIVE, EVENT_SUPERSEDE): STATUS_SUPERSEDED,
    (STATUS_ACTIVE, EVENT_INVALIDATE): STATUS_INVALIDATED,
}

INVALIDATION_SOURCES = ("user_clarification", "new_evidence", "judge")


class IllegalTransitionError(Exception):
    def __init__(self, status: str, event: str):
        super().__init__(f"非法状态转换: {status} --{event}--> ?")
        self.status = status
        self.event = event


def transition(status: str, event: str) -> str:
    try:
        return TRANSITIONS[(status, event)]
    except KeyError:
        raise IllegalTransitionError(status, event) from None


def invalidate_insight(
    insight_id: str, reason: str, source: str = "user_clarification", trace=None
) -> bool:
    """active→invalidated；已 invalidated 幂等 no-op 返回 True；superseded 终态互斥拒绝。"""
    started = time.perf_counter()
    text = (reason or "").strip()
    if not text:
        raise ValueError("invalidated_reason 必填")
    if source not in INVALIDATION_SOURCES:
        raise ValueError(f"非法失效来源: {source}")
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(InsightRow, insight_id)
        if row is None:
            _trace(trace, started, event=EVENT_INVALIDATE, insight_id=insight_id, status="miss")
            return False
        if row.status == STATUS_INVALIDATED:
            _trace(trace, started, event=EVENT_INVALIDATE, insight_id=insight_id, status="noop")
            return True
        if row.status == STATUS_SUPERSEDED:
            _trace(
                trace,
                started,
                event=EVENT_INVALIDATE,
                insight_id=insight_id,
                status="rejected",
                reason="superseded 为终态",
            )
            return False
        row.status = transition(row.status, EVENT_INVALIDATE)
        row.invalidated_at = now
        row.invalidated_reason = f"{source}:{text}"
        row.updated_at = now
        session.commit()
    _trace(trace, started, event=EVENT_INVALIDATE, insight_id=insight_id, status="ok")
    return True


def supersede_insight(old_id: str, new_id: str, reason: str = "", trace=None) -> bool:
    """active→superseded（superseded_by 指向新行）；新行须存在且 active。"""
    started = time.perf_counter()
    with SessionLocal() as session:
        old_row = session.get(InsightRow, old_id)
        new_row = session.get(InsightRow, new_id)
        if (
            old_row is None
            or new_row is None
            or old_row.status != STATUS_ACTIVE
            or new_row.status != STATUS_ACTIVE
        ):
            _trace(
                trace,
                started,
                event=EVENT_SUPERSEDE,
                insight_id=old_id,
                superseded_by=new_id,
                status="rejected",
            )
            return False
        old_row.status = transition(old_row.status, EVENT_SUPERSEDE)
        old_row.superseded_by = new_id
        old_row.updated_at = datetime.now()
        session.commit()
    _trace(
        trace,
        started,
        event=EVENT_SUPERSEDE,
        insight_id=old_id,
        superseded_by=new_id,
        reason=reason,
        status="ok",
    )
    return True


def get_insight(insight_id: str) -> Insight | None:
    with SessionLocal() as session:
        row = session.get(InsightRow, insight_id)
        return _to_insight(row) if row is not None else None


def list_active_insights(
    user_id: str,
    character_id: str = "asuna",
    min_confidence: float = 0.0,
    scopes: list[str] | None = None,
    limit: int = 20,
) -> list[Insight]:
    """active Insight 只读查询（confidence DESC, created_at DESC）；REF-007 消费。"""
    settings = get_settings()
    threshold = (
        min_confidence if min_confidence is not None else settings.v2_reflection_min_confidence
    )
    with SessionLocal() as session:
        query = session.query(InsightRow).filter(
            InsightRow.user_id == user_id,
            InsightRow.status == STATUS_ACTIVE,
            InsightRow.character_id.in_([character_id, "*"]),
            InsightRow.confidence >= threshold,
        )
        if scopes:
            query = query.filter(InsightRow.scope.in_(list(scopes)))
        rows = (
            query.order_by(InsightRow.confidence.desc(), InsightRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_insight(row) for row in rows]


def _to_insight(row: InsightRow) -> Insight:
    return Insight(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        statement=row.statement,
        type=row.type,
        confidence=row.confidence,
        scope=row.scope,
        status=row.status,
        run_id=row.run_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        invalidated_at=row.invalidated_at,
        invalidated_reason=row.invalidated_reason,
        superseded_by=row.superseded_by,
    )


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)
