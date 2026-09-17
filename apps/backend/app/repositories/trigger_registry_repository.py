"""trigger_registry 持久化触发登记表仓储（LIFE-001）。

状态机 pending→due→fired→done|cancelled；trigger_key 唯一防重复登记
（与 v1 dedupe_key 同形）。重检型触发（inactivity/action_due）经
register_and_claim 在单事务内完成「登记+领取+上一轮交接补记」；一次性
followup 走 register + claim_due_followups 领取。所有迁移比较基于调用方
注入的 now（禁散落 datetime.now()）。
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Sequence

from sqlalchemy import or_

from app.core.db import SessionLocal, TriggerRegistryRow

logger = logging.getLogger(__name__)

PRIORITY_BY_TYPE = {
    "action_due": 1,
    "scheduled_followup": 2,
    "conversation_inactivity": 3,
}
ACTIVE_STATUSES = ("pending", "due", "fired")
TERMINAL_STATUSES = ("done", "cancelled")


def _now(now: datetime | None) -> datetime:
    return now or datetime.now()


def get(trigger_key: str) -> TriggerRegistryRow | None:
    with SessionLocal() as session:
        return (
            session.query(TriggerRegistryRow)
            .filter(TriggerRegistryRow.trigger_key == trigger_key)
            .first()
        )


def list_recent(user_id: str | None = None, limit: int = 50) -> list[TriggerRegistryRow]:
    with SessionLocal() as session:
        query = session.query(TriggerRegistryRow)
        if user_id is not None:
            query = query.filter(TriggerRegistryRow.user_id == user_id)
        return (
            query.order_by(TriggerRegistryRow.updated_at.desc()).limit(limit).all()
        )


def register(
    user_id: str,
    trigger_type: str,
    trigger_key: str,
    due_at: datetime,
    payload: dict | None = None,
    character_id: str = "asuna",
    now: datetime | None = None,
) -> str:
    """登记触发（upsert）：无行→pending；活动态→原样（更新 due_at/payload）；
    终态→复活 pending。返回登记后状态。"""
    now = _now(now)
    with SessionLocal() as session:
        row = (
            session.query(TriggerRegistryRow)
            .filter(TriggerRegistryRow.trigger_key == trigger_key)
            .with_for_update()
            .first()
        )
        if row is None:
            session.add(
                TriggerRegistryRow(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    character_id=character_id,
                    trigger_type=trigger_type,
                    trigger_key=trigger_key,
                    status="pending",
                    due_at=due_at,
                    priority=PRIORITY_BY_TYPE.get(trigger_type, 3),
                    attempt_count=0,
                    payload=payload or {},
                    created_at=now,
                    updated_at=now,
                )
            )
            status = "pending"
        else:
            row.due_at = due_at
            if payload:
                row.payload = payload
            if row.status in TERMINAL_STATUSES:
                is_action_schedule = (
                    trigger_type == "action_due"
                    and str(trigger_key).startswith("action_schedule:")
                ) or (payload or {}).get("kind") == "action_schedule"
                if is_action_schedule:
                    logger.info(
                        "action_schedule 终态不复活 trigger_key=%s status=%s",
                        trigger_key,
                        row.status,
                    )
                    return row.status
                row.status = "pending"
            status = row.status
            row.updated_at = now
        session.commit()
        return status


def register_and_claim(
    user_id: str,
    trigger_type: str,
    trigger_key: str,
    due_at: datetime,
    payload: dict | None = None,
    character_id: str = "asuna",
    now: datetime | None = None,
) -> TriggerRegistryRow | None:
    """重检型触发的登记+领取（单事务）。

    无行 → 建 pending 并领取；pending 且到期 → 领取；due/fired（上一轮
    交接已被同步 tick 消费）→ 补记 done 后重新领取；done/cancelled →
    复活并领取。未到期或领取竞争失败返回 None。
    """
    now = _now(now)
    with SessionLocal() as session:
        row = (
            session.query(TriggerRegistryRow)
            .filter(TriggerRegistryRow.trigger_key == trigger_key)
            .with_for_update()
            .first()
        )
        if row is None:
            row = TriggerRegistryRow(
                id=str(uuid.uuid4()),
                user_id=user_id,
                character_id=character_id,
                trigger_type=trigger_type,
                trigger_key=trigger_key,
                status="pending",
                due_at=due_at,
                priority=PRIORITY_BY_TYPE.get(trigger_type, 3),
                attempt_count=0,
                payload=payload or {},
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.due_at = due_at
            if payload:
                row.payload = payload
            if row.status != "pending":
                row.status = "pending"
        if row.status == "pending" and (
            row.cooldown_until is None or row.cooldown_until <= now
        ):
            row.status = "due"
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return row
        session.rollback()
        return None


def claim_due_followups(
    user_id: str, now: datetime | None = None, limit: int = 5
) -> list[TriggerRegistryRow]:
    """领取到期 followup（pending→due 原子交接，状态守卫防并发双领取）。"""
    now = _now(now)
    claimed: list[TriggerRegistryRow] = []
    with SessionLocal() as session:
        candidates = (
            session.query(TriggerRegistryRow)
            .filter(
                TriggerRegistryRow.user_id == user_id,
                TriggerRegistryRow.trigger_type == "scheduled_followup",
                TriggerRegistryRow.status == "pending",
                TriggerRegistryRow.due_at <= now,
            )
            .order_by(TriggerRegistryRow.priority, TriggerRegistryRow.due_at)
            .limit(limit)
            .all()
        )
        for row in candidates:
            if row.cooldown_until is not None and row.cooldown_until > now:
                continue
            updated = (
                session.query(TriggerRegistryRow)
                .filter(
                    TriggerRegistryRow.id == row.id,
                    TriggerRegistryRow.status == "pending",
                )
                .update({"status": "due", "updated_at": now})
            )
            if updated:
                session.refresh(row)
                claimed.append(row)
        session.commit()
    return claimed


def mark_fired(trigger_key: str, now: datetime | None = None) -> bool:
    """due→fired（信号已交接给决策管线）。"""
    now = _now(now)
    with SessionLocal() as session:
        updated = (
            session.query(TriggerRegistryRow)
            .filter(
                TriggerRegistryRow.trigger_key == trigger_key,
                TriggerRegistryRow.status == "due",
            )
            .update({"status": "fired", "updated_at": now})
        )
        session.commit()
        return bool(updated)


def complete(trigger_key: str, now: datetime | None = None) -> bool:
    """due/fired→done（下游终态；幂等，pending/due 前置态之外不动）。"""
    now = _now(now)
    with SessionLocal() as session:
        updated = (
            session.query(TriggerRegistryRow)
            .filter(
                TriggerRegistryRow.trigger_key == trigger_key,
                TriggerRegistryRow.status.in_(("due", "fired")),
            )
            .update({"status": "done", "updated_at": now})
        )
        session.commit()
        return bool(updated)


def force_done(trigger_key: str, now: datetime | None = None) -> bool:
    """任意非终态 → done（action_schedule 执行成功收口）。"""
    now = _now(now)
    with SessionLocal() as session:
        updated = (
            session.query(TriggerRegistryRow)
            .filter(
                TriggerRegistryRow.trigger_key == trigger_key,
                TriggerRegistryRow.status.notin_(TERMINAL_STATUSES),
            )
            .update({"status": "done", "updated_at": now})
        )
        session.commit()
        return bool(updated)


def force_cancelled(trigger_key: str, now: datetime | None = None) -> bool:
    """任意非终态 → cancelled（action_schedule 放弃收口）。"""
    now = _now(now)
    with SessionLocal() as session:
        updated = (
            session.query(TriggerRegistryRow)
            .filter(
                TriggerRegistryRow.trigger_key == trigger_key,
                TriggerRegistryRow.status.notin_(TERMINAL_STATUSES),
            )
            .update({"status": "cancelled", "updated_at": now})
        )
        session.commit()
        return bool(updated)


def fail_for_retry(
    trigger_key: str,
    reason: str,
    now: datetime | None = None,
    max_attempts: int = 3,
    backoff_seconds: int = 300,
) -> str:
    """due/fired→pending 重试（attempt+1 + 指数退避冷却）；达上限转 cancelled 死信。

    返回迁移后状态：pending / cancelled / unchanged（行不在可重试态）。
    """
    now = _now(now)
    with SessionLocal() as session:
        row = (
            session.query(TriggerRegistryRow)
            .filter(TriggerRegistryRow.trigger_key == trigger_key)
            .with_for_update()
            .first()
        )
        if row is None or row.status not in ("due", "fired"):
            return "unchanged"
        attempts = row.attempt_count + 1
        row.attempt_count = attempts
        row.last_error = reason[:500]
        row.updated_at = now
        if attempts >= max_attempts:
            row.status = "cancelled"
        else:
            row.status = "pending"
            row.cooldown_until = now + timedelta(
                seconds=backoff_seconds * (2 ** (attempts - 1))
            )
        session.commit()
        return row.status


def cancel(trigger_key: str, reason: str, now: datetime | None = None) -> bool:
    """任一活动态→cancelled（stale / max_attempts / 显式取消；终态幂等不动）。"""
    now = _now(now)
    with SessionLocal() as session:
        updated = (
            session.query(TriggerRegistryRow)
            .filter(
                TriggerRegistryRow.trigger_key == trigger_key,
                TriggerRegistryRow.status.in_(ACTIVE_STATUSES),
            )
            .update(
                {"status": "cancelled", "last_error": reason[:500], "updated_at": now}
            )
        )
        session.commit()
        return bool(updated)


def has_due(
    user_id: str | None = None,
    now: datetime | None = None,
    include_types: Sequence[str] | None = None,
    exclude_payload_kinds: Sequence[str] | None = None,
) -> bool:
    """是否存在到期待领取触发（pending 且 due_at≤now 且冷却已过）。

    Idle 判定（LIFE-003）用 include_types 排除 conversation_inactivity——
    重检型触发逐 tick 重检测，恒有 pending 行会令 Idle 永不命中。

    `exclude_payload_kinds`（P2-1，可选）：按 `payload.kind` 排除"借表的非待办行"。
    V2.4.0 的确认请求 / 授权行复用本表（`trigger_type = action_due`，判别位在
    `payload.kind`），`due_at` 只用于表达 TTL——从到期到清理的窗口里若被计入
    "到期待办触发"，会令自治 tick 多跑一轮。调用侧（`life_loop`）**仅在工具总闸开启时**
    传入 `("tool_confirmation", "tool_grant")`。

    `payload` 缺 `kind` 键的行（V9 既有 action_due 行）**必须仍被计入**，故条件写成
    "kind IS NULL OR kind NOT IN (...)"；`None`（默认）时**不加该条件**，SQL 与行为与
    V9 逐字节一致。
    """
    now = _now(now)
    with SessionLocal() as session:
        query = session.query(TriggerRegistryRow.id).filter(
            TriggerRegistryRow.status == "pending",
            TriggerRegistryRow.due_at <= now,
        )
        if user_id is not None:
            query = query.filter(TriggerRegistryRow.user_id == user_id)
        if include_types is not None:
            query = query.filter(TriggerRegistryRow.trigger_type.in_(include_types))
        kinds = [
            str(kind) for kind in (exclude_payload_kinds or ()) if str(kind)
        ]
        if kinds:
            payload_kind = TriggerRegistryRow.payload["kind"].as_string()
            query = query.filter(
                or_(payload_kind.is_(None), ~payload_kind.in_(kinds))
            )
        return session.query(query.exists()).scalar()


def recover_stale(
    now: datetime | None = None,
    timeout_seconds: int = 600,
    max_attempts: int = 3,
    backoff_seconds: int = 300,
) -> int:
    """对账：due/fired 滞留超时的行回 pending 重试（或达上限 cancelled）。"""
    now = _now(now)
    cutoff = now - timedelta(seconds=timeout_seconds)
    with SessionLocal() as session:
        stuck = (
            session.query(TriggerRegistryRow)
            .filter(
                TriggerRegistryRow.status.in_(("due", "fired")),
                TriggerRegistryRow.updated_at <= cutoff,
            )
            .all()
        )
        keys = [row.trigger_key for row in stuck]
    recovered = 0
    for key in keys:
        status = fail_for_retry(
            key,
            reason="stale_recovered",
            now=now,
            max_attempts=max_attempts,
            backoff_seconds=backoff_seconds,
        )
        if status in ("pending", "cancelled"):
            recovered += 1
    return recovered
