"""Outbox 只读门面（RT-ALL-code-review H-3）。

`application` 层不得直读 `app.repositories`；跨域可靠投递的**读**面收口到这里，
写面仍归 `app/application/outbox_consumer.py` 与各域合法通道（Outbox 一致性模型零改动）。

只读：本模块不含任何写操作。
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.repositories import outbox_repository

logger = logging.getLogger(__name__)


def list_pending(now: datetime | None = None, limit: int = 50) -> list:
    """到期待消费行（`pending` 且 `next_retry_at ≤ now`，FIFO）。"""
    try:
        return outbox_repository.list_pending(now=now, limit=limit)
    except Exception:
        logger.exception("outbox 待消费行读取失败，降级为空集")
        return []
