"""Shared Experience 只读投影（REL-002）。

三源（relationship_events 账本 + memories(experience/relationship_fact) + 完结
world_events 双人参与项）归并为时间序共同经历：账本行是事件时序权威，叙事记忆
经 source_ref 回指并入对应账本条目（账本给结构、记忆给叙事）。同数据同投影、
零写路径、可随时重算（domain-boundaries §2 Projection）。
"""

import logging
from datetime import datetime

from app.core import timeutil
from app.core.settings import get_settings
from app.models.relationship import SharedExperience
from app.repositories import (
    memory_repository,
    relationship_event_repository,
    world_repository,
)

logger = logging.getLogger(__name__)

_LEDGER_EVENT_LIMIT = 100
_MEMORY_LIMIT = 200
_WORLD_EVENT_LIMIT = 50
_TITLE_MAX_CHARS = 60


def _enum(value):
    return getattr(value, "value", value)


def _title(text: str | None, fallback: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        cleaned = fallback
    return cleaned[:_TITLE_MAX_CHARS]


def _ledger_entries(user_id: str) -> list[SharedExperience]:
    entries: list[SharedExperience] = []
    for event in relationship_event_repository.list_events(
        user_id, limit=_LEDGER_EVENT_LIMIT
    ):
        if event.type == "none":
            continue
        # 「排除派生行（原 memory_replay）」过滤已随该源值退役删除（2026-10-16）：
        # `RelationshipEventSource` 只剩 conversation / system，投影自然只含真实互动行。
        entries.append(
            SharedExperience(
                entry_id=event.id,
                kind="relationship_event",
                title=_title(event.cause, "一次互动"),
                occurred_at=timeutil.ensure_aware(event.created_at),
                source_ref={"table": "relationship_events", "id": event.id},
                salience=event.confidence,
            )
        )
    return entries


def _memory_entries(
    user_id: str, character_id: str, min_salience: float
) -> list[SharedExperience]:
    rows = memory_repository.list_active_by_types(
        user_id, character_id, ["experience", "relationship_fact"], limit=_MEMORY_LIMIT
    )
    refs = memory_repository.get_source_refs([row.id for row in rows])
    entries: list[SharedExperience] = []
    for row in rows:
        ref = refs.get(row.id) or {}
        salience = row.importance
        if row.type == "experience" and salience < min_salience:
            continue
        entry = SharedExperience(
            entry_id=row.id,
            kind=row.type,
            title=_title(row.content, "一段相处"),
            occurred_at=timeutil.ensure_aware(row.created_at),
            source_ref={
                "table": ref.get("table") or "memories",
                "id": ref.get("id") or row.id,
            },
            salience=salience,
        )
        if ref.get("table") == "relationship_events" and ref.get("id"):
            entry.ledger_event_id = ref["id"]
        entries.append(entry)
    return entries


def _world_entries(user_id: str) -> list[SharedExperience]:
    world_id = world_repository.find_world_id(user_id)
    if world_id is None:
        return []
    events = world_repository.list_events(
        world_id, statuses=["completed"], limit=_WORLD_EVENT_LIMIT
    )
    entries: list[SharedExperience] = []
    for event in events:
        source = _enum(event.source)
        importance = _enum(event.importance)
        if source != "user_mention" or importance == "low":
            continue
        entries.append(
            SharedExperience(
                entry_id=event.id,
                kind="world_event",
                title=_title(event.title, "一段共同经历"),
                occurred_at=timeutil.ensure_aware(
                    event.completed_at or event.created_at or datetime.min
                ),
                source_ref={"table": "world_events", "id": event.id},
                salience=0.8 if importance == "high" else 0.6,
            )
        )
    return entries


def _merge(
    ledger: list[SharedExperience], memories: list[SharedExperience]
) -> list[SharedExperience]:
    """叙事记忆并入其 source_ref 指向的账本条目（title 优先记忆叙事）。"""
    by_event = {entry.entry_id: entry for entry in ledger}
    merged: list[SharedExperience] = []
    for entry in memories:
        target = by_event.get(entry.ledger_event_id) if entry.ledger_event_id else None
        if target is not None:
            target.title = entry.title
            continue
        merged.append(entry)
    merged.extend(ledger)
    return merged


def collect_shared_experiences(
    user_id: str, character_id: str = "asuna", now: datetime | None = None
) -> list[SharedExperience]:
    """三源归并的时间序共同经历投影；单源异常按空降级，不阻塞其余源。"""
    settings = get_settings()
    ledger: list[SharedExperience] = []
    memories: list[SharedExperience] = []
    world: list[SharedExperience] = []
    try:
        ledger = _ledger_entries(user_id)
    except Exception:
        logger.exception("共同经历投影：账本源查询失败，按空处理")
    try:
        memories = _memory_entries(
            user_id, character_id, settings.relationship_shared_min_salience
        )
    except Exception:
        logger.exception("共同经历投影：记忆源查询失败，按空处理")
    try:
        world = _world_entries(user_id)
    except Exception:
        logger.exception("共同经历投影：世界事件源查询失败，按空处理")
    merged = _merge(ledger, memories)
    merged.extend(world)
    merged.sort(key=lambda entry: (entry.occurred_at, entry.entry_id))
    return merged
