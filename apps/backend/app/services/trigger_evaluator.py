"""V7 TriggerEvaluator（trigger-model.md §2~3）。

MVP 仅 conversation_inactivity；scheduled_followup 类型已在模型层预留（V7-010 P1 实现）。
纯函数：会话末条消息信息 + episode 记账 → TriggerSignal | None。
"""

from dataclasses import dataclass
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
