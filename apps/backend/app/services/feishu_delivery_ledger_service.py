"""飞书出站投递幂等的**持久化路径**（FEISHU-011，多实例硬前置之一）。

`delivery._delivered` 是进程内表：多 worker / 多实例下同一逻辑消息会被每个实例各投
一次（重复回复用户）。本模块把占位判定落到 `feishu_deliveries` 表的主键唯一约束上，
提供跨进程原子判定。

**分层**：通道层不得 import `app.repositories`（依赖 allowlist fail-closed），故本模块
由组合根（`app/main.py`）通过 `delivery.set_persistent_idempotency()` 注入。

**失败语义 fail-open**：存储不可用时**放行投递**并记 warning。出站幂等的收益是省掉
重复发送；fail-closed 会让用户**收不到任何回复**——重复一条消息远比静默不回可接受。
（与入站去重同取向：宁可重复，不能丢。）
"""

import asyncio
import logging
import threading
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.repositories import feishu_delivery_ledger_repository

logger = logging.getLogger(__name__)

PURGE_EVERY = 256

_purge_ops = 0
_purge_lock = threading.Lock()


def reset_delivery_ledger_state() -> None:
    global _purge_ops
    with _purge_lock:
        _purge_ops = 0


def idempotency_ttl_seconds() -> int:
    """与 `delivery._idempotency_ttl_seconds` **必须一致**（由用例锁死）。

    窗口是出站幂等的语义边界，两处若漂移会出现「内存路径已过期、DB 路径仍判重」
    这类极难察觉的差异。
    """
    settings = get_settings()
    return (
        settings.feishu_outbound_idempotency_ttl_seconds
        or settings.feishu_dedupe_ttl_seconds
    )


def _claim_sync(key: str) -> bool:
    ttl = idempotency_ttl_seconds()
    now = datetime.now()
    try:
        claimed = feishu_delivery_ledger_repository.claim(
            key, now, now - timedelta(seconds=ttl)
        )
    except Exception:
        logger.warning(
            "feishu persistent outbound idempotency unavailable, sending anyway (fail-open): "
            "key=%s",
            key,
            exc_info=True,
        )
        return True
    if claimed:
        _maybe_purge(now, ttl)
    return claimed


async def claim(key: str) -> bool:
    """占位入口（供 `delivery` 注入）；DB 调用下放线程，不阻塞事件循环。"""
    return await asyncio.to_thread(_claim_sync, key)


async def release(key: str) -> None:
    """回滚占位；失败只记 warning（占位残留会在 TTL 后自然淘汰）。"""
    try:
        await asyncio.to_thread(feishu_delivery_ledger_repository.release, key)
    except Exception:
        logger.warning(
            "feishu persistent outbound idempotency release failed (ignored): key=%s",
            key,
            exc_info=True,
        )


def _maybe_purge(now: datetime, ttl: int) -> None:
    """摊还清理：每 PURGE_EVERY 次成功占位清一次过期行，控制表规模。"""
    global _purge_ops
    with _purge_lock:
        _purge_ops += 1
        if _purge_ops % PURGE_EVERY:
            return
    try:
        removed = feishu_delivery_ledger_repository.purge_before(
            now - timedelta(seconds=ttl)
        )
    except Exception:
        logger.warning(
            "feishu persistent outbound idempotency purge failed (ignored)", exc_info=True
        )
        return
    if removed:
        logger.info("feishu persistent outbound idempotency purged rows: count=%d", removed)
