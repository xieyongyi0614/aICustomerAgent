"""V7 TriggerEvaluator（trigger-model.md §2~4）。

conversation_inactivity 纯函数判定；scheduled_followup 内存登记表（低频、重启丢失可接受）。
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime

from app.core.settings import get_settings
from app.models.autonomy import TriggerSignal


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
    key = dedupe_key or f"followup:{user_id}:{summary[:20]}:{due_at.date().isoformat()}"
    with _followup_lock:
        _followup_registry[key] = {
            "user_id": user_id,
            "due_at": due_at,
            "summary": summary,
        }
    return key


def find_followup_event(content: str) -> str | None:
    """记忆内容含事件关键词时返回摘要（memory 管线登记点用）。"""
    content = content or ""
    for keyword in FOLLOWUP_EVENT_KEYWORDS:
        if keyword in content:
            return keyword
    return None


def poll_due_followup(user_id: str, now: datetime) -> TriggerSignal | None:
    """tick 内惰性求值：due_at ≤ now 的登记项产出信号并出队。"""
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


def evaluate_inactivity(
    tail: SessionTail,
    user_id: str,
    episode_attempts: int = 0,
    seen_keys: set[str] | None = None,
    now: datetime | None = None,
    config=None,
) -> TriggerSignal | None:
    config = config or get_settings()
    now = now or datetime.now()
    seen_keys = seen_keys or set()

    if tail.last_message_at is None:
        return None
    if (
        tail.last_message_role == "human"
        and tail.last_user_message_at is not None
        and (now - tail.last_user_message_at).total_seconds() / 60
        < config.autonomy_min_user_reply_gap_minutes
    ):
        return None
    idle_minutes = (now - tail.last_message_at).total_seconds() / 60
    if idle_minutes < config.autonomy_inactivity_minutes:
        return None
    if episode_attempts >= config.autonomy_max_attempts_per_episode:
        return None
    if tail.last_user_message_id is None:
        return None
    dedupe_key = f"inactivity:{user_id}:{tail.last_user_message_id}"
    if dedupe_key in seen_keys:
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
