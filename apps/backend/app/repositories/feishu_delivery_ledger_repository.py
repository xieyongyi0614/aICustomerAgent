"""feishu_deliveries 单表数据访问（FEISHU-011）：跨进程出站投递幂等。

`idempotency_key` 主键即幂等键。判定用「插入 + 主键冲突」而非「先查再插」——后者在
两个实例同时投递同一逻辑消息时会双双判定为「未投递」而各发一次。

TTL 语义：主键约束不知道「过期」，故 `claim` 先摘除该键的过期行再插入，使判定与
进程内表的 TTL 语义一致（过期即可重新投递）。
"""

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core import ids
from app.core.db import FeishuDeliveryRow, SessionLocal

logger = logging.getLogger(__name__)


def claim(key: str, delivered_at: datetime, expired_before: datetime) -> bool:
    """占位一个幂等键；返回 True 表示本次为**首次**投递。"""
    row = FeishuDeliveryRow(
        id=ids.new_id_str(), idempotency_key=key, delivered_at=delivered_at
    )
    try:
        with SessionLocal() as session:
            session.query(FeishuDeliveryRow).filter(
                FeishuDeliveryRow.idempotency_key == key,
                FeishuDeliveryRow.delivered_at < expired_before,
            ).delete(synchronize_session=False)
            session.add(row)
            session.commit()
    except IntegrityError:
        return False
    return True


def release(key: str) -> None:
    """回滚占位（发送失败时调用），使重试仍可继续。"""
    with SessionLocal() as session:
        session.query(FeishuDeliveryRow).filter(
            FeishuDeliveryRow.idempotency_key == key
        ).delete(synchronize_session=False)
        session.commit()


def purge_before(cutoff: datetime) -> int:
    """删除 `delivered_at < cutoff` 的行，返回删除条数（摊还清理）。"""
    with SessionLocal() as session:
        removed = (
            session.query(FeishuDeliveryRow)
            .filter(FeishuDeliveryRow.delivered_at < cutoff)
            .delete(synchronize_session=False)
        )
        session.commit()
        return removed


def exists(key: str) -> bool:
    with SessionLocal() as session:
        return (
            session.query(FeishuDeliveryRow.idempotency_key)
            .filter(FeishuDeliveryRow.idempotency_key == key)
            .first()
            is not None
        )
