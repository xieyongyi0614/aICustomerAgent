"""V7 TriggerEvaluator（trigger-model.md §2~4）。

conversation_inactivity 纯函数判定；scheduled_followup 内存登记表（低频、重启丢失可接受）。
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime

from app.core import timeutil
from app.core.settings import get_settings
from app.models.autonomy import TriggerSignal
from app.repositories import trigger_registry_repository, world_repository

logger = logging.getLogger(__name__)


@dataclass
class SessionTail:
    """会话末尾快照：最后一条消息 + 用户最后一条消息（episode 起点）。"""

    last_message_at: datetime | None = None
    last_message_role: str | None = None
    last_user_message_at: datetime | None = None
    last_user_message_id: str | None = None


FOLLOWUP_EVENT_KEYWORDS = ("面试", "考试", "会议", "答辩", "体检")

_followup_registry: dict[str, dict] = {}
_followup_lock = threading.Lock()


def register_followup(
    user_id: str, due_at: datetime, summary: str, dedupe_key: str | None = None
) -> str:
    key = dedupe_key or f"followup:{user_id}:{summary[:20]}:{timeutil.local(due_at).date().isoformat()}"
    with _followup_lock:
        _followup_registry[key] = {
            "user_id": user_id,
            "due_at": due_at,
            "summary": summary,
        }
    try:
        trigger_registry_repository.register(
            user_id=user_id,
            trigger_type="scheduled_followup",
            trigger_key=key,
            due_at=due_at,
            payload={"summary": summary},
        )
    except Exception:
        logger.exception("followup 登记表写入失败，留存内存路径：%s", key)
    return key


def find_followup_event(content: str) -> str | None:
    """记忆内容含事件关键词时返回摘要（memory 管线登记点用）。"""
    content = content or ""
    for keyword in FOLLOWUP_EVENT_KEYWORDS:
        if keyword in content:
            return keyword
    return None


def _poll_due_followup_registry(user_id: str, now: datetime) -> TriggerSignal | None:
    """LIFE-001 表通道：领取到期 followup（pending→due→fired→done 一次性消费）。"""

    rows = trigger_registry_repository.claim_due_followups(user_id, now=now)
    if not rows:
        return None
    row = rows[0]
    trigger_registry_repository.mark_fired(row.trigger_key, now=now)
    trigger_registry_repository.complete(row.trigger_key, now=now)
    with _followup_lock:
        _followup_registry.pop(row.trigger_key, None)
    payload = row.payload or {}
    return TriggerSignal(
        type="scheduled_followup",
        user_id=user_id,
        detected_at=now,
        context={
            "summary": str(payload.get("summary", "")),
            "due_at": row.due_at.isoformat(),
        },
        dedupe_key=row.trigger_key,
    )


def poll_due_followup(user_id: str, now: datetime) -> TriggerSignal | None:
    """tick 内惰性求值：due_at ≤ now 的登记项产出信号并出队。

    Flag ON 时表通道优先（跨重启持久）；未命中或表异常回退内存路径
    （迁移窗口内 drain 遗留 dict 登记项）。
    """
    try:
        signal = _poll_due_followup_registry(user_id, now)
    except Exception:
        logger.exception("followup 登记表轮询失败，回退内存路径")
        signal = None
    if signal is not None:
        return signal
    due: str | None = None
    with _followup_lock:
        for key, item in _followup_registry.items():
            if item["user_id"] == user_id and item["due_at"] <= now:
                due = key
                break
        if due is not None:
            item = _followup_registry.pop(due)
        else:
            return None
    return TriggerSignal(
        type="scheduled_followup",
        user_id=user_id,
        detected_at=now,
        context={"summary": item["summary"], "due_at": item["due_at"].isoformat()},
        dedupe_key=due,
    )


def poll_due_actions(user_id: str, now: datetime) -> TriggerSignal | None:
    """V9 due_action 触发器（autonomy-integration.md §3，H-A6）。

    active 的 reminder/appointment 到期且未汇报（payload 无 reported_by_autonomy）→
    产出 action_due 信号。只读查询，置位由 mark_action_reported 在投递成功后完成，
    保证静音/冷却期间的到期提醒顺延到可汇报时。无行动时返回 None。
    """
    try:
        world = world_repository.get_world(user_id)
        if world is None:
            return None
        for event in world_repository.list_events(
            world.world_id, statuses=["active"], limit=50
        ):
            if event.type not in ("reminder", "appointment"):
                continue
            if event.due_at is None or event.due_at > now:
                continue
            if (event.payload or {}).get("reported_by_autonomy"):
                continue
            try:
                claimed = trigger_registry_repository.register_and_claim(
                    user_id=user_id,
                    trigger_type="action_due",
                    trigger_key=f"action_due:{event.id}",
                    due_at=now,
                    payload={
                        "event_id": event.id,
                        "title": event.title,
                        "due_at": event.due_at.isoformat(),
                    },
                    now=now,
                )
            except Exception:
                logger.exception("action_due 登记领取失败，按 v1 行为放行")
                claimed = True
            if not claimed:
                continue
            return TriggerSignal(
                type="action_due",
                user_id=user_id,
                detected_at=now,
                context={
                    "event_id": event.id,
                    "title": event.title,
                    "due_at": event.due_at.isoformat(),
                },
                dedupe_key=f"action_due:{event.id}",
            )
    except Exception:
        logger.exception("到期行动轮询失败，跳过")
    return None


def mark_action_reported(user_id: str, event_id: str) -> None:
    """到期行动已由自治汇报过：置 world 事件 payload.reported_by_autonomy（幂等）。"""
    try:
        world = world_repository.get_world(user_id)
        if world is None:
            return
        now = timeutil.now()
        for event in world_repository.list_events(
            world.world_id, statuses=["active"], limit=50
        ):
            if event.id != event_id:
                continue
            event.payload = {**(event.payload or {}), "reported_by_autonomy": True}
            event.updated_at = now
            world_repository.save_event(event)
            try:
                trigger_registry_repository.complete(
                    f"action_due:{event_id}", now=now
                )
            except Exception:
                logger.exception("action_due trigger 完成标记失败（幂等可重入）")
            return
    except Exception:
        logger.exception("到期行动汇报标记失败")


def evaluate_inactivity(
    tail: SessionTail,
    user_id: str,
    episode_attempts: int = 0,
    seen_keys: set[str] | None = None,
    now: datetime | None = None,
    config=None,
) -> TriggerSignal | None:
    config = config or get_settings()
    now = timeutil.ensure_aware(now) or timeutil.now()
    seen_keys = seen_keys or set()

    if tail.last_message_at is None:
        return None
    if (
        tail.last_message_role == "human"
        and tail.last_user_message_at is not None
        and (now - timeutil.ensure_aware(tail.last_user_message_at)).total_seconds() / 60
        < config.autonomy_min_user_reply_gap_minutes
    ):
        return None
    idle_minutes = (
        now - timeutil.ensure_aware(tail.last_message_at)
    ).total_seconds() / 60
    if idle_minutes < config.autonomy_inactivity_minutes:
        return None
    if episode_attempts >= config.autonomy_max_attempts_per_episode:
        return None
    if tail.last_user_message_id is None:
        return None
    dedupe_key = f"inactivity:{user_id}:{tail.last_user_message_id}"
    if dedupe_key in seen_keys:
        return None
    try:
        claimed = trigger_registry_repository.register_and_claim(
            user_id=user_id,
            trigger_type="conversation_inactivity",
            trigger_key=dedupe_key,
            due_at=now,
            payload={
                "idle_minutes": round(idle_minutes, 1),
                "last_role": tail.last_message_role,
                "last_user_message_id": tail.last_user_message_id,
            },
            now=now,
        )
    except Exception:
        logger.exception("inactivity 登记领取失败，按 v1 行为放行")
    else:
        if claimed is None:
            return None
    return TriggerSignal(
        type="conversation_inactivity",
        user_id=user_id,
        detected_at=now,
        context={
            "idle_minutes": round(idle_minutes, 1),
            "last_role": tail.last_message_role,
        },
        dedupe_key=dedupe_key,
    )
