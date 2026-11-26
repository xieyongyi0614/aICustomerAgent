"""V8 Memory Bridge（memory-integration.md §2~§4）：完结事件 → 记忆候选单向投递。

候选构造沿用本模块边界表（阈值门 / 类型映射 / 过期文案），写入统一经
memory.ingest.create_candidate 投 v2 候选（通道收敛第 3 批，禁止直写 memories），
由 v2 评估器转正。边界：低重要度事件不沉淀；物品/环境状态永远只存 World。
"""

import logging
from datetime import datetime

from app.core import timeutil
from app.core.settings import get_settings
from app.models.world import EventImportance, EventStatus, WorldEvent
from app.repositories import world_repository
from app.services.memory import ingest as memory_ingest

logger = logging.getLogger(__name__)

EVENT_MEMORY_TYPES = {
    "interview": "experience",
    "exam": "experience",
    "appointment": "experience",
    "trip": "experience",
    "meeting": "experience",
    "birthday": "user_fact",
}

EVENT_SOURCE_MAP = {"user_mention": "user_derived", "manual": "user_derived", "autonomy": "ai_inferred"}


def to_memory_candidates(event: WorldEvent) -> list[dict]:
    settings = get_settings()
    thresholds = settings.world_memory_importance()
    threshold = float(thresholds.get(event.importance.value, 0.0))
    if threshold <= 0.0:
        return []
    moment = event.completed_at or event.due_at or timeutil.now()
    if event.status is EventStatus.EXPIRED:
        started = event.started_at or event.due_at or timeutil.now()
        return [
            {
                "content": (
                    f"用户在{started.strftime('%m月%d日')}提到过{event.title}，"
                    f"后来没有完成，已过期"
                ),
                "memory_type": EVENT_MEMORY_TYPES.get(event.type, "experience"),
                "importance": min(threshold, 0.5),
                "confidence": 0.7,
            }
        ]
    return [
        {
            "content": f"用户在{moment.strftime('%m月%d日')}完成了{event.title}",
            "memory_type": EVENT_MEMORY_TYPES.get(event.type, "experience"),
            "importance": threshold,
            "confidence": 0.8,
        }
    ]


def materialize_event_memory(event: WorldEvent, user_id: str, character_id: str = "asuna") -> bool:
    """幂等投递：payload.memory_materialized 防重；v2 候选键 (world_events, event.id) 二次防重。

    投递不落库：记忆经 v2 评估转正后可见。失败只 log。
    """
    if event.payload.get("memory_materialized"):
        return False
    try:
        candidates = to_memory_candidates(event)
        invested = False
        for candidate in candidates:
            memory_ingest.create_candidate(
                user_id=user_id,
                character_id=character_id,
                source_table=memory_ingest.SOURCE_WORLD,
                source_id=event.id,
                content=candidate["content"],
                proposed_type=candidate["memory_type"],
                source_kind=EVENT_SOURCE_MAP.get(event.source.value, "ai_inferred"),
                salience_init=candidate["importance"],
                source_ref_extra={
                    "world_id": event.world_id,
                    "importance": candidate["importance"],
                    "confidence": candidate["confidence"],
                },
            )
            invested = True
        payload = dict(event.payload)
        payload["memory_materialized"] = True
        event.payload = payload
        event.updated_at = timeutil.now()
        world_repository.save_event(event)
        return invested
    except Exception:
        logger.exception("事件记忆沉淀失败，已忽略")
        return False
