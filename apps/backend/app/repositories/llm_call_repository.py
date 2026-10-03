"""V7.8 llm_call_records 仓储（llm-observability.md §4）。

每次调用点调用一行；retention 惰性清理在 save 路径顺带执行。
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func

from app.core.db import LlmCallRecordRow, SessionLocal
from app.core.settings import get_settings
from app.models.observability import CallSite, LlmCallRecord, estimate_cost

logger = logging.getLogger(__name__)


def _to_model(row: LlmCallRecordRow) -> LlmCallRecord:
    return LlmCallRecord(
        id=row.id,
        request_id=row.request_id,
        turn_id=row.turn_id,
        call_site=CallSite(row.call_site),
        profile_id=row.profile_id,
        model=row.model,
        provider=row.provider,
        status=row.status,
        latency_ms=row.latency_ms or 0.0,
        ttft_ms=row.ttft_ms,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cost_estimate=row.cost_estimate,
        error_kind=row.error_kind,
        started_at=row.started_at,
        created_at=row.created_at,
    )


def _from_model(record: LlmCallRecord, created_at: datetime) -> LlmCallRecordRow:
    return LlmCallRecordRow(
        id=record.id,
        request_id=record.request_id,
        turn_id=record.turn_id,
        call_site=record.call_site.value if hasattr(record.call_site, "value") else str(record.call_site),
        profile_id=record.profile_id,
        model=record.model,
        provider=record.provider,
        status=record.status,
        latency_ms=record.latency_ms,
        ttft_ms=record.ttft_ms,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cost_estimate=record.cost_estimate,
        error_kind=record.error_kind,
        started_at=record.started_at,
        created_at=created_at,
    )


def _finalize_cost(record: LlmCallRecord) -> LlmCallRecord:
    if record.cost_estimate is not None:
        return record
    cost = estimate_cost(record.model, record.input_tokens, record.output_tokens, get_settings().observability_llm_cost_table())
    if cost is None:
        return record
    return record.model_copy(update={"cost_estimate": cost})


def save(record: LlmCallRecord) -> None:
    record = _finalize_cost(record)
    now = datetime.now()
    try:
        with SessionLocal() as session:
            session.merge(_from_model(record, now))
            session.commit()
    except Exception:
        logger.exception("LLM 调用记录落库失败，已忽略")
        return
    prune_before(now - timedelta(days=get_settings().observability_llm_call_retention_days))


def get_by_request(request_id: str, limit: int = 100) -> list[LlmCallRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(LlmCallRecordRow)
            .filter(LlmCallRecordRow.request_id == request_id)
            .order_by(LlmCallRecordRow.created_at.asc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def get_by_turn(turn_id: str, limit: int = 100) -> list[LlmCallRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(LlmCallRecordRow)
            .filter(LlmCallRecordRow.turn_id == turn_id)
            .order_by(LlmCallRecordRow.created_at.asc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def search(
    request_id: str | None = None,
    turn_id: str | None = None,
    since: datetime | None = None,
    call_site: str | None = None,
    model: str | None = None,
    limit: int = 100,
) -> list[LlmCallRecord]:
    with SessionLocal() as session:
        query = session.query(LlmCallRecordRow)
        if request_id is not None:
            query = query.filter(LlmCallRecordRow.request_id == request_id)
        if turn_id is not None:
            query = query.filter(LlmCallRecordRow.turn_id == turn_id)
        if since is not None:
            query = query.filter(LlmCallRecordRow.created_at >= since)
        if call_site is not None:
            query = query.filter(LlmCallRecordRow.call_site == call_site)
        if model is not None:
            query = query.filter(LlmCallRecordRow.model == model)
        rows = (
            query.order_by(LlmCallRecordRow.created_at.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        return [_to_model(row) for row in rows]


def list_since(cutoff: datetime, limit: int = 20000) -> list[LlmCallRecord]:
    with SessionLocal() as session:
        rows = (
            session.query(LlmCallRecordRow)
            .filter(LlmCallRecordRow.created_at >= cutoff)
            .order_by(LlmCallRecordRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def prune_before(cutoff: datetime) -> int:
    with SessionLocal() as session:
        deleted = (
            session.query(LlmCallRecordRow)
            .filter(LlmCallRecordRow.created_at < cutoff)
            .delete()
        )
        session.commit()
        return deleted


def aggregate_usage_since(cutoff: datetime) -> dict:
    """日配额聚合（LIFE-003）：调用次数 + 总 token，走 idx_llm_calls_time。"""
    with SessionLocal() as session:
        calls, tokens = (
            session.query(
                func.count(LlmCallRecordRow.id),
                func.coalesce(
                    func.sum(
                        func.coalesce(LlmCallRecordRow.input_tokens, 0)
                        + func.coalesce(LlmCallRecordRow.output_tokens, 0)
                    ),
                    0,
                ),
            )
            .filter(LlmCallRecordRow.created_at >= cutoff)
            .one()
        )
        return {"calls": int(calls), "tokens": int(tokens)}


def count_calls_by_request(request_id: str) -> int:
    """按 trace `request_id` **精确归因**的 LLM 调用数（RT-ALL-code-review M-7）。

    与 `count_calls_between` 的区别：时间窗计数在**并发 Run** 下会把别的 Run 的调用
    也算进来（互相重复记账）；`request_id` 由该 Run 自己的 trace 生成，故是精确归因。
    `llm_calls` 无 `run_id` 列（不新增列 → 不破 V3.0 G5「仅 0052 两列」），
    故以 trace 为归因锚点；无 trace 的路径（自治 tick）仍用窗口计数，属近似。
    """
    if not request_id:
        return 0
    with SessionLocal() as session:
        return int(
            session.query(func.count(LlmCallRecordRow.id))
            .filter(LlmCallRecordRow.request_id == request_id)
            .scalar()
            or 0
        )


def count_calls_between(start: datetime, end: datetime) -> int:
    """run 窗口内 LLM 调用计数（loop_runs llm_call_count 记账用）。"""
    with SessionLocal() as session:
        return int(
            session.query(func.count(LlmCallRecordRow.id))
            .filter(
                LlmCallRecordRow.created_at >= start,
                LlmCallRecordRow.created_at <= end,
            )
            .scalar()
            or 0
        )
