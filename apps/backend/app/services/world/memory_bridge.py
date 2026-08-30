"""V8 Memory Bridge（memory-integration.md §2~§4）：完结事件 → 记忆候选单向投递。

只调用既有 memory 仓储写入口；V4 extractor/policy 零改动。
边界：低重要度事件不沉淀；物品/环境状态永远只存 World。
"""

import logging
from datetime import datetime

from app.core.settings import get_settings
from app.models.world import EventImportance, WorldEvent

logger = logging.getLogger(__name__)

EVENT_MEMORY_TYPES = {
    "interview": "important_event",
    "exam": "important_event",
    "appointment": "important_event",
    "trip": "important_event",
    "meeting": "important_event",
    "birthday": "user_fact",
}

EVENT_SOURCE_MAP = {"user_mention": "user_derived", "manual": "user_derived", "autonomy": "ai_inferred"}


def to_memory_candidates(event: WorldEvent) -> list[dict]:
    settings = get_settings()
    thresholds = settings.world_memory_importance()
    threshold = float(thresholds.get(event.importance.value, 0.0))
    if threshold <= 0.0:
        return []
    moment = event.completed_at or event.due_at or datetime.now()
    return [
        {
            "content": f"用户在{moment.strftime('%m月%d日')}完成了{event.title}",
            "memory_type": EVENT_MEMORY_TYPES.get(event.type, "important_event"),
            "importance": threshold,
            "confidence": 0.8,
        }
    ]


def materialize_event_memory(event: WorldEvent, user_id: str, character_id: str = "asuna") -> bool:
    """幂等投递：payload.memory_materialized 防重；失败只 log。"""
    if event.payload.get("memory_materialized"):
        return False
    try:
        from app.repositories import memory_repository, world_repository

        candidates = to_memory_candidates(event)
        written = False
        for candidate in candidates:
            memory_repository.create_memory(
                user_id=user_id,
                character_id=character_id,
                content=candidate["content"],
                memory_type=candidate["memory_type"],
                importance=candidate["importance"],
                confidence=candidate["confidence"],
                source=EVENT_SOURCE_MAP.get(event.source.value, "ai_inferred"),
            )
            written = True
        payload = dict(event.payload)
        payload["memory_materialized"] = True
        event.payload = payload
        event.updated_at = datetime.now()
        world_repository.save_event(event)
        return written
    except Exception:
        logger.exception("事件记忆沉淀失败，已忽略")
        return False
