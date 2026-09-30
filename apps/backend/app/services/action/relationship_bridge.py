"""V9 Action Relationship Bridge（relationship-impact.md §2~§5，V9-008）。

V9 零直写 RelationshipState：信号经既有 apply_relationship_v5（三层钳制）
+ commit_relationship_update 通道投递；门控 action_relationship_enabled 默认关。
"""

import logging
from datetime import datetime

from app.character.asuna.action import ACTION_RELATIONSHIP_MAP
from app.core.settings import get_settings
from app.models.action import ActionRecord
from app.models.relationship import RelationshipDelta, RelationshipEvent
from app.repositories import relationship_event_repository, relationship_repository
from app.engines import state as state_engine
from app.services.conversation.state import _day_impact_totals

logger = logging.getLogger(__name__)


def lookup_signal(record: ActionRecord) -> tuple[str, str] | None:
    """信号映射纯函数（角色资产表）：无行即不投递。"""
    if record.status != "succeeded":
        return None
    return ACTION_RELATIONSHIP_MAP.get((record.action_type, record.source, "succeeded"))


def _same_turn_dialog_user_help(record: ActionRecord, events: list) -> bool:
    """防双计：同 turn 内对话 user_help 已存在时行动信号让位。"""
    if record.session_id is None:
        return False
    return any(
        event.type == "user_help"
        and event.source != "action"
        and getattr(event, "session_id", None) == record.session_id
        for event in events
    )


def deliver_action_signal(record: ActionRecord, user_id: str) -> dict | None:
    """投递入口：门控 + 映射 + 钳制 + 落库。失败只 log。"""
    settings = get_settings()
    if not settings.action_relationship_enabled:
        return None
    try:
        signal = lookup_signal(record)
        if signal is None:
            return None
        event_type, magnitude = signal
        events = relationship_event_repository.list_events(user_id, limit=500)
        if _same_turn_dialog_user_help(record, events):
            return None
        now = datetime.now()
        relationship = relationship_repository.get_relationship(user_id)
        day_positive, day_negative = _day_impact_totals(user_id, now, events=events)
        new_relationship, applied = state_engine.apply_relationship_v5(
            relationship,
            event_type,
            magnitude,
            "normal_reply",
            day_positive,
            day_negative,
        )
        event = RelationshipEvent(
            user_id=user_id,
            session_id=record.session_id or "",
            type=event_type,
            magnitude=magnitude,
            impact=applied if isinstance(applied, RelationshipDelta) else RelationshipDelta(),
            confidence=0.8,
            cause=f"行动 {record.action_type} {record.status}"[:50],
            created_at=now,
        )
        relationship_repository.commit_relationship_update(user_id, new_relationship, [event])
        return {"event_type": event_type, "magnitude": magnitude}
    except Exception:
        logger.exception("行动关系信号投递失败（不回滚行动）")
        return None
