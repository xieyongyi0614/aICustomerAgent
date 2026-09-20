"""飞书入站去重的**持久化路径**（FEISHU-010，多实例硬前置之一）。

多 worker / 多实例下进程内去重表（`channels/feishu/events._seen_events`）无法共享，
同一 `event_id` 会被每个实例各受理一次（重复 LLM 调用 + 重复回复）。本模块把判定
落到 `feishu_dedupe_ledger` 表的主键唯一约束上，提供跨进程原子判定。

**分层**：通道层保持纯函数、不感知存储；由组合根（`api/v1/feishu.py`）按
`FEISHU_DEDUPE_PERSISTENT_ENABLED` 选择内存表还是本模块（`app/channels/**` 的
依赖 allowlist 是 fail-closed 的，不得反向 import `app.repositories`）。

**失败语义 fail-open**：存储不可用时**放行**并记 warning。去重的收益是省掉重复
处理，而 fail-closed 会直接丢掉用户消息——宁可重复调用一次 LLM，也不要静默丢
消息。（与限流取向相反：限流失败应保守拒绝以保护 LLM。）
"""

import logging
import threading
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.repositories import feishu_dedupe_ledger_repository

logger = logging.getLogger(__name__)

PURGE_EVERY = 256

_purge_ops = 0
_purge_lock = threading.Lock()


def reset_dedupe_service_state() -> None:
    global _purge_ops
    with _purge_lock:
        _purge_ops = 0


def claim(event_id: str) -> bool:
    """返回 True 表示本次为**首次**受理（可继续处理）。存储异常时放行（fail-open）。"""
    ttl = get_settings().feishu_dedupe_ttl_seconds
    now = datetime.now()
    try:
        claimed = feishu_dedupe_ledger_repository.claim(
            event_id, now, now - timedelta(seconds=ttl)
        )
    except Exception:
        logger.warning(
            "feishu persistent dedupe unavailable, accepting event (fail-open): event_id=%s",
            event_id,
            exc_info=True,
        )
        return True
    if claimed:
        _maybe_purge(now, ttl)
    return claimed


def _maybe_purge(now: datetime, ttl: int) -> None:
    """摊还清理：每 PURGE_EVERY 次成功占位清一次过期行，控制表规模。"""
    global _purge_ops
    with _purge_lock:
        _purge_ops += 1
        if _purge_ops % PURGE_EVERY:
            return
    try:
        removed = feishu_dedupe_ledger_repository.purge_before(now - timedelta(seconds=ttl))
    except Exception:
        logger.warning("feishu persistent dedupe purge failed (ignored)", exc_info=True)
        return
    if removed:
        logger.info("feishu persistent dedupe purged expired rows: count=%d", removed)
