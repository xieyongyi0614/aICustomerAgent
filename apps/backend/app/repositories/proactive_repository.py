"""V7 proactive_actions 仓储（action-queue.md Outbox 语义 + cooldown.md 记账）。

单用户深度 1；状态机单向；dedupe_key 幂等。
"""

import logging
from datetime import datetime

from app.core.db import ProactiveActionRow, SessionLocal
from app.models.autonomy import TERMINAL_STATUSES, ProactiveAction

logger = logging.getLogger(__name__)

EXECUTABLE_STATUSES = ("candidate", "approved")
PENDING_STATUSES = ("delivered",)
PENDING_EXPIRE_HOURS = 24

_TRANSITIONS: dict[str, frozenset[str]] = {
    "candidate": frozenset({"approved", "discarded"}),
    "approved": frozenset({"delivered", "failed", "discarded", "candidate"}),
    "failed": frozenset({"approved", "delivered", "failed", "discarded"}),
    "delivered": frozenset({"acked", "expired"}),
}


def _to_model(row: ProactiveActionRow) -> ProactiveAction:
    return ProactiveAction(
        id=row.id,
        user_id=row.user_id,
        character_id=row.character_id,
        session_id=row.session_id,
        type=row.type,
        trigger_type=row.trigger_type,
        dedupe_key=row.dedupe_key,
        goal_id=row.goal_id,
        intention=row.intention,
        reason=row.reason,
        payload_text=row.payload_text,
        status=row.status,
        attempt=row.attempt,
        next_retry_at=row.next_retry_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        delivered_at=row.delivered_at,
        message_id=row.message_id,
        acked_at=row.acked_at,
    )


def enqueue(action: ProactiveAction) -> bool:
    """candidate 行落库；同 user 存在任意非终态行（深度 1）或同 dedupe_key 已处理过则拒绝。"""
    now = datetime.now()
    with SessionLocal() as session:
        blocking = (
            session.query(ProactiveActionRow)
            .filter(
                ProactiveActionRow.user_id == action.user_id,
                ProactiveActionRow.status.notin_(TERMINAL_STATUSES),
            )
            .first()
        )
        if blocking is not None:
            return False
        deduped = (
            session.query(ProactiveActionRow)
            .filter(
                ProactiveActionRow.user_id == action.user_id,
                ProactiveActionRow.dedupe_key == action.dedupe_key,
                ProactiveActionRow.status.notin_(frozenset({"discarded"})),
            )
            .first()
        )
        if deduped is not None:
            return False
        session.add(
            ProactiveActionRow(
                id=action.id,
                user_id=action.user_id,
                character_id=action.character_id,
                session_id=action.session_id,
                type=action.type,
                trigger_type=action.trigger_type,
                dedupe_key=action.dedupe_key,
                goal_id=action.goal_id,
                intention=action.intention,
                reason=action.reason,
                payload_text=action.payload_text,
                status="candidate",
                attempt=action.attempt,
                next_retry_at=action.next_retry_at,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
        return True


def get_active(user_id: str, now: datetime | None = None) -> ProactiveAction | None:
    """可执行的非终态行：candidate/approved，或重试到期的 failed（终态 failed 无 next_retry_at，不取）。"""
    now = now or datetime.now()
    with SessionLocal() as session:
        rows = (
            session.query(ProactiveActionRow)
            .filter(
                ProactiveActionRow.user_id == user_id,
                ProactiveActionRow.status.in_(["candidate", "approved", "failed"]),
            )
            .order_by(ProactiveActionRow.created_at.desc())
            .all()
        )
        for row in rows:
            if row.status == "failed":
                if row.next_retry_at is None or row.next_retry_at > now:
                    continue
            return _to_model(row)
        return None


def has_non_terminal(user_id: str) -> bool:
    with SessionLocal() as session:
        return (
            session.query(ProactiveActionRow)
            .filter(
                ProactiveActionRow.user_id == user_id,
                ProactiveActionRow.status.notin_(TERMINAL_STATUSES),
            )
            .first()
            is not None
        )


def transition(
    action_id: str,
    to_status: str,
    now: datetime | None = None,
    **fields,
) -> ProactiveAction | None:
    """状态机校验的单步迁移；非法迁移返回 None。"""
    now = now or datetime.now()
    with SessionLocal() as session:
        row = session.get(ProactiveActionRow, action_id)
        if row is None:
            return None
        allowed = _TRANSITIONS.get(row.status, frozenset())
        if to_status not in allowed:
            logger.warning(
                "非法主动行为状态迁移：%s %s→%s", action_id, row.status, to_status
            )
            return None
        row.status = to_status
        row.updated_at = now
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()
        session.refresh(row)
        return _to_model(row)


def get_by_id(action_id: str) -> ProactiveAction | None:
    with SessionLocal() as session:
        row = session.get(ProactiveActionRow, action_id)
        return _to_model(row) if row is not None else None


def list_pending(user_id: str, now: datetime | None = None) -> list[ProactiveAction]:
    """delivered 未 acked；超 24h 未 ack 惰性置 expired（软状态审计）。"""
    now = now or datetime.now()
    with SessionLocal() as session:
        rows = (
            session.query(ProactiveActionRow)
            .filter(ProactiveActionRow.user_id == user_id)
            .order_by(ProactiveActionRow.delivered_at.desc())
            .all()
        )
        result = []
        changed = False
        for row in rows:
            if row.status == "delivered" and row.delivered_at is not None:
                idle_hours = (now - row.delivered_at).total_seconds() / 3600
                if idle_hours >= PENDING_EXPIRE_HOURS:
                    row.status = "expired"
                    row.updated_at = now
                    changed = True
                    continue
            if row.status in PENDING_STATUSES:
                result.append(_to_model(row))
        if changed:
            session.commit()
        return result


def aggregate_episode(
    user_id: str, episode_start: datetime
) -> tuple[datetime | None, int]:
    """返回 (last_proactive_at, episode 内 delivered 次数)，cooldown.md §2 记账口径。"""
    with SessionLocal() as session:
        rows = (
            session.query(ProactiveActionRow)
            .filter(
                ProactiveActionRow.user_id == user_id,
                ProactiveActionRow.status.in_(["delivered", "acked"]),
                ProactiveActionRow.delivered_at.isnot(None),
            )
            .order_by(ProactiveActionRow.delivered_at.desc())
            .all()
        )
        last_proactive_at = rows[0].delivered_at if rows else None
        attempt_count = sum(
            1 for row in rows if row.delivered_at is not None and row.delivered_at >= episode_start
        )
        return last_proactive_at, attempt_count


def reset_on_user_message(user_id: str, now: datetime | None = None) -> None:
    """用户发言复位（cooldown.md §5）：delivered 未 acked → acked；candidate/approved → discarded。"""
    now = now or datetime.now()
    with SessionLocal() as session:
        rows = (
            session.query(ProactiveActionRow)
            .filter(
                ProactiveActionRow.user_id == user_id,
                ProactiveActionRow.status.in_(["candidate", "approved", "delivered"]),
            )
            .all()
        )
        for row in rows:
            if row.status == "delivered":
                row.status = "acked"
                row.acked_at = now
            else:
                row.status = "discarded"
            row.updated_at = now
        if rows:
            session.commit()


def list_users_with_history() -> list[str]:
    with SessionLocal() as session:
        rows = session.query(ProactiveActionRow.user_id).distinct().all()
        return [row.user_id for row in rows]


def list_delivered_history(user_id: str, limit: int = 10) -> list[ProactiveAction]:
    """delivered/acked 历史（新→旧），供事后时机审计取前次投递与集期记账。"""
    with SessionLocal() as session:
        rows = (
            session.query(ProactiveActionRow)
            .filter(
                ProactiveActionRow.user_id == user_id,
                ProactiveActionRow.status.in_(["delivered", "acked"]),
                ProactiveActionRow.delivered_at.isnot(None),
            )
            .order_by(ProactiveActionRow.delivered_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]


def list_since(cutoff: datetime, limit: int = 5000) -> list[ProactiveAction]:
    with SessionLocal() as session:
        rows = (
            session.query(ProactiveActionRow)
            .filter(ProactiveActionRow.created_at >= cutoff)
            .order_by(ProactiveActionRow.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_to_model(row) for row in rows]
