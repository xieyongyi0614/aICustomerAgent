"""feishu_dedupe_ledger 单表数据访问（FEISHU-010）：跨进程入站事件去重。

`event_id` 主键即幂等键。判定用「插入 + 主键冲突」而非「先查再插」——后者在
两个实例同时到达同一 `event_id` 时会双双判定为「未见过」而各处理一次，正是
本表要消除的缺陷。

TTL 语义：主键约束本身不知道「过期」，故 `claim` 先摘除该 `event_id` 的过期行
再插入，使判定与进程内表的 TTL 语义一致（过期即可重新受理）。
"""

import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.core.db import FeishuDedupeLedgerRow, SessionLocal

logger = logging.getLogger(__name__)


def claim(event_id: str, received_at: datetime, expired_before: datetime) -> bool:
    """占位一个 `event_id`；返回 True 表示本次为**首次**受理。

    先删同 id 的过期行、再插入：两条语句在同一事务内，唯一约束由数据库保证，
    故多进程/多实例下同样原子。
    """
    row = FeishuDedupeLedgerRow(event_id=event_id, received_at=received_at)
    try:
        with SessionLocal() as session:
            session.query(FeishuDedupeLedgerRow).filter(
                FeishuDedupeLedgerRow.event_id == event_id,
                FeishuDedupeLedgerRow.received_at < expired_before,
            ).delete(synchronize_session=False)
            session.add(row)
            session.commit()
    except IntegrityError:
        return False
    return True


def purge_before(cutoff: datetime) -> int:
    """删除 `received_at < cutoff` 的行，返回删除条数（摊还清理，控制表规模）。"""
    with SessionLocal() as session:
        removed = (
            session.query(FeishuDedupeLedgerRow)
            .filter(FeishuDedupeLedgerRow.received_at < cutoff)
            .delete(synchronize_session=False)
        )
        session.commit()
        return removed


def exists(event_id: str) -> bool:
    with SessionLocal() as session:
        return (
            session.query(FeishuDedupeLedgerRow.event_id)
            .filter(FeishuDedupeLedgerRow.event_id == event_id)
            .first()
            is not None
        )
