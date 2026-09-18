"""V2.3.0 CharacterEventBridge（architecture.md §5.4 角色事件源）。

方向：角色域状态变更 → outbox（事务惯例）→ outbox_consumer → world_events。
Flag 关闭时零登记；outbox 幂等键防重；消费失败走既有重试/死信。
"""

import logging

from app.core.settings import get_settings
from app.repositories import outbox_repository

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    settings = get_settings()
    return settings.world_simulation_enabled and settings.event_detection_enabled


def _register_world_op(
    user_id: str,
    event_type: str,
    title: str,
    importance: str,
    payload: dict,
    idempotency_key: str,
) -> bool:
    if not _enabled():
        return False
    op = {
        "op": "create_event",
        "args": [
            user_id,
            event_type,
            title,
            importance,
            None,
            "character",
            "completed",
            payload,
            idempotency_key,
        ],
    }
    try:
        return outbox_repository.insert(
            {"world_ops": [op], "applied_ops": 0}, idempotency_key
        )
    except Exception:
        logger.exception("角色事件 outbox 登记失败：%s", idempotency_key)
        return False


def register_goal_event(user_id: str, goal_id: str, description: str, outcome: str) -> bool:
    if outcome == "completed":
        title = f"完成了目标：{description[:50]}"
        importance = "normal"
    else:
        title = f"放下了目标：{description[:50]}"
        importance = "low"
    return _register_world_op(
        user_id,
        "goal_completed",
        title,
        importance,
        {"goal_id": goal_id, "outcome": outcome, "description": description[:50]},
        f"char:goal_done:{goal_id}",
    )


def register_interest_event(
    user_id: str, insight_id: str, topic: str, confidence: float
) -> bool:
    return _register_world_op(
        user_id,
        "interest_emerged",
        f"对新事物产生兴趣：{topic[:50]}",
        "normal",
        {"insight_id": insight_id, "topic": topic[:50], "confidence": confidence},
        f"char:interest:{insight_id}",
    )


def on_insight_created(user_id: str, created: list[dict]) -> None:
    """insight_created 订阅：self 域高置信 Insight → interest_emerged。"""
    threshold = get_settings().interest_confidence_threshold
    for item in created or []:
        insight_id = item.get("insight_id")
        if not insight_id:
            continue
        if item.get("scope") != "self":
            continue
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            continue
        if confidence < threshold:
            continue
        topic = str(item.get("summary") or item.get("conclusion") or "未知主题")
        register_interest_event(user_id, insight_id, topic, confidence)


def register_character_event_listeners() -> None:
    """main.lifespan 注册入口；Flag 关闭即零注册零行为。"""
    if not _enabled():
        return
    from app.services.reflection import lifecycle as reflection_lifecycle

    reflection_lifecycle.register_insight_created_listener(on_insight_created)
