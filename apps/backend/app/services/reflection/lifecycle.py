"""Insight 生命周期（REF-001 + REF-005 策略层）。

状态机 active→superseded|invalidated（两终态互斥、不复活、非法转换拒绝），
与 memory 状态机同构但独立实现（Reflection 只写本域三表，不 import memory）。
迁移 API 全部单事务：条件 UPDATE 带 status='active'，影响 0 行即 no-op，天然幂等。
invalidated_reason 必填由服务层前置校验 + DB CHECK 兜底；supersede 要求新行存在
且 active，不产生悬挂引用。原行不删除（审计保留）。

REF-005 策略层：澄清话语 ↔ Insight 匹配（LCS 归一相似度，阈值高于记忆冲突侧，
唯一高匹配才失效——保守防误失效）；find_superseded_insights 供 REF-004 入库事务
选择替代目标；失效事件钩子（迁移成功才回调，P3 DEV-004 订阅，P2 空注册零行为）。
"""

import logging
import time
import uuid
from datetime import datetime

from app.core.db import InsightRow, SessionLocal
from app.core.settings import get_settings
from app.models.reflection import Insight
from app.engines.memory_conflict import _lcs_length

logger = logging.getLogger(__name__)

STEP_NAME = "reflection_lifecycle"
INVALIDATE_STEP_NAME = "reflection_invalidate"

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
        notify_invalidation_listeners(
            row.user_id,
            [
                {
                    "insight_id": row.id,
                    "status": STATUS_INVALIDATED,
                    "invalidated_reason": row.invalidated_reason,
                }
            ],
        )
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
        notify_invalidation_listeners(
            old_row.user_id,
            [
                {
                    "insight_id": old_row.id,
                    "status": STATUS_SUPERSEDED,
                    "superseded_by": new_id,
                }
            ],
        )
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
        min_confidence if min_confidence is not None else settings.reflection_min_confidence
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


_invalidation_listeners: list = []
_insight_created_listeners: list = []


def register_invalidation_listener(fn) -> None:
    """失效事件订阅点（P3 DEV-004 接线）；P2 无注册方即零行为。"""
    _invalidation_listeners.append(fn)


def reset_invalidation_listeners() -> None:
    _invalidation_listeners.clear()


def notify_invalidation_listeners(user_id: str, changed: list[dict]) -> None:
    """迁移成功后广播；监听器异常尽力而为，不影响已完成的迁移。"""
    if not _invalidation_listeners or not changed:
        return
    for listener in list(_invalidation_listeners):
        try:
            listener(user_id, changed)
        except Exception:
            logger.exception("失效事件监听器异常，已忽略")


def register_insight_created_listener(fn) -> None:
    """创建事件订阅点（P3 DEV-002 编译触发接线）；无注册方即零行为。"""
    _insight_created_listeners.append(fn)


def reset_insight_created_listeners() -> None:
    _insight_created_listeners.clear()


def notify_insight_created_listeners(user_id: str, created: list[dict]) -> None:
    """新 active Insight 落库后广播；监听器异常尽力而为，不影响已完成的落库。"""
    if not _insight_created_listeners or not created:
        return
    for listener in list(_insight_created_listeners):
        try:
            listener(user_id, created)
        except Exception:
            logger.exception("Insight 创建事件监听器异常，已忽略")


def statement_similarity(left: str, right: str) -> float:
    longer = max(len(left or ""), len(right or ""))
    if longer == 0:
        return 0.0
    return _lcs_length(left or "", right or "") / longer


def match_insights_for_invalidation(
    content: str, actives: list[Insight], threshold: float | None = None
) -> list[Insight]:
    """澄清内容 ↔ active Insight 相似度匹配；返回达到阈值的候选（降序）。"""
    threshold = (
        threshold
        if threshold is not None
        else get_settings().reflection_invalidate_match_threshold
    )
    scored = [
        (insight, statement_similarity(content, insight.statement))
        for insight in actives
    ]
    matched = [item for item in scored if item[1] >= threshold]
    matched.sort(key=lambda item: item[1], reverse=True)
    return [insight for insight, _sim in matched]


def observe_negation(
    user_id: str, memory_id: str, content: str, trace=None
) -> list[str]:
    """澄清通道：唯一高匹配 → invalidated；多匹配/低匹配/无匹配保守忽略（0 LLM）。"""
    started = time.perf_counter()
    settings = get_settings()
    threshold = settings.reflection_invalidate_match_threshold
    with SessionLocal() as session:
        rows = (
            session.query(InsightRow)
            .filter(InsightRow.user_id == user_id, InsightRow.status == STATUS_ACTIVE)
            .all()
        )
        actives = [_to_insight(row) for row in rows]
    scores = [
        (insight, round(statement_similarity(content, insight.statement), 4))
        for insight in actives
    ]
    matches = [
        (insight, score) for insight, score in scores if score >= threshold
    ]
    matches.sort(key=lambda item: item[1], reverse=True)
    if len(matches) != 1:
        _invalidate_trace(
            trace,
            started,
            memory_id=memory_id,
            decision="ignored",
            reason="ambiguous" if len(matches) > 1 else "no_match",
            match_count=len(matches),
            candidates=[{"insight_id": i.id, "score": s} for i, s in scores][:10],
        )
        return []
    target, score = matches[0]
    changed = invalidate_insight(
        target.id,
        f"澄清:{(content or '').strip()[:60]}|ref:{memory_id}",
        source="user_clarification",
        trace=trace,
    )
    _invalidate_trace(
        trace,
        started,
        memory_id=memory_id,
        decision="invalidated" if changed else "noop",
        reason=f"similarity={score}",
        match_count=1,
        insight_id=target.id,
    )
    return [target.id] if changed else []


def find_superseded_insights(
    new_statement: str,
    new_scope: str,
    new_type: str,
    actives: list[Insight],
    threshold: float | None = None,
) -> list[str]:
    """替代策略：同 scope+type 且相似度达阈值（替代是更强结论，阈值与失效同源）。"""
    threshold = (
        threshold
        if threshold is not None
        else get_settings().reflection_invalidate_match_threshold
    )
    return [
        insight.id
        for insight in actives
        if insight.scope == new_scope
        and insight.type == new_type
        and statement_similarity(new_statement, insight.statement) >= threshold
    ]


def list_user_active_insights(user_id: str) -> list[Insight]:
    """失效匹配候选集：该用户全部 active Insight（scope 不过滤——澄清话语不带 scope 标签）。"""
    with SessionLocal() as session:
        rows = (
            session.query(InsightRow)
            .filter(InsightRow.user_id == user_id, InsightRow.status == STATUS_ACTIVE)
            .all()
        )
        return [_to_insight(row) for row in rows]


def _trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(STEP_NAME, duration, status, **extra)


def _invalidate_trace(trace, started: float, *, status: str = "ok", **extra) -> None:
    if trace is None:
        return
    duration = (time.perf_counter() - started) * 1000
    trace.record(INVALIDATE_STEP_NAME, duration, status, **extra)
