"""V2.0.0 LIFE-004 outbox 消费器。

三段各自事务（data-flow.md §2.1）：world 段（逐 op 调既有引擎函数落库，
applied_ops 进度标记崩溃重放续走）→ relationship 段（既有 bridge）→
CAS pending→consumed；记忆候选由 P1 摄取补扫按 (source_table, source_id)
幂等收敛（本消费器不直接投递记忆）。单行失败不影响批内其他行；
连续失败指数退避 max5 → failed 死信（debug 可查，ops 决策重置）。
"""

import logging
from datetime import datetime

from app.core.settings import get_settings
from app.models.action import ActionRecord
from app.repositories import outbox_repository, world_repository
from app.application import world_engine
from app.services.action import relationship_bridge

logger = logging.getLogger(__name__)


def consume_pending(limit: int = 50, now: datetime | None = None) -> dict:
    """消费到期待处理行；返回批统计（scanned/consumed/retried/dead_lettered）。"""
    settings = get_settings()
    now = now or datetime.now()
    rows = outbox_repository.list_pending(now=now, limit=limit)
    stats = {
        "scanned": len(rows),
        "consumed": 0,
        "retried": 0,
        "dead_lettered": 0,
    }
    for row in rows:
        try:
            _apply_outbox_row(row)
        except Exception as exc:
            logger.exception("outbox 消费失败：%s", row.idempotency_key)
            status = outbox_repository.fail_for_retry(
                row.idempotency_key,
                reason=str(exc),
                now=now,
                max_attempts=settings.v2_life_loop_outbox_max_attempts,
                backoff_seconds=settings.v2_life_loop_outbox_backoff_seconds,
            )
            if status == "failed":
                stats["dead_lettered"] += 1
            else:
                stats["retried"] += 1
            continue
        if outbox_repository.mark_consumed(row.idempotency_key, now=now):
            stats["consumed"] += 1
    return stats


def _apply_outbox_row(row) -> None:
    payload = row.payload or {}
    ops = payload.get("world_ops") or []
    applied = int(payload.get("applied_ops", 0))
    for op in ops[applied:]:
        _apply_world_op(row.idempotency_key, op)
        applied += 1
        outbox_repository.advance_progress(row.idempotency_key, applied)

    if not payload.get("relationship_done"):
        record_payload = payload.get("record")
        if record_payload:
            record = ActionRecord(**record_payload)
            relationship_bridge.deliver_action_signal(record, record.user_id)
        outbox_repository.mark_relationship_done(row.idempotency_key)


_ISO_DATETIME_PREFIX = "0000-01-01T00:00:00"


def _restore_datetimes(args: list) -> list:
    """JSON 序列化还原：ISO 8601 形状的字符串参数还原为 datetime。"""

    def _convert(value):
        if isinstance(value, str) and len(value) >= 19 and value[10] in ("T", " "):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return value
        return value

    return [_convert(arg) for arg in args]


def _apply_world_op(action_id: str, op: dict) -> None:
    """单 world op 落库（引擎函数原样）；create_event 成功后打 outbox_action_id
    指纹（重放幂等护栏）；引擎返回 None = 世界侧失败 → 抛错进入重试/死信。"""
    op_name = str(op.get("op", ""))
    args = _restore_datetimes(op.get("args") or [])
    if not hasattr(world_engine, op_name):
        raise RuntimeError(f"未知 world op: {op_name}")
    result = getattr(world_engine, op_name)(*args)
    if op_name == "create_event" and result is not None:
        result.payload = {**(result.payload or {}), "outbox_action_id": action_id}
        world_repository.save_event(result)
    elif result is None:
        raise RuntimeError(f"world op {op_name} 落库失败（容量上限或世界不可用）")
