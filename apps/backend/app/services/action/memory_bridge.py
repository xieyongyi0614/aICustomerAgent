"""V9 Action Memory Bridge（memory-policy.md §2~§4，V9-007）。

行动记忆第四供给方：候选经既有 memory_policy R1~R8 校验（零豁免）后由
memory_repository 落库；source 只用 user_stated / user_derived。
"""

import logging

from app.character.asuna.action import (
    ACTION_MEMORY_TEMPLATES,
    REMINDER_BIRTHDAY_KEYWORDS,
)
from app.core.settings import get_settings
from app.models.action import ActionRecord
from app.models.memory import MemoryCandidate
from app.repositories import memory_repository
from app.services import memory_policy

logger = logging.getLogger(__name__)


def _template(action_type: str, params: dict) -> str:
    template = ACTION_MEMORY_TEMPLATES.get(action_type)
    if template is None:
        return ""
    return template.format(**{key: str(value) for key, value in params.items()})


def to_memory_candidates(record: ActionRecord) -> list[MemoryCandidate]:
    """边界表纯函数：ActionRecord → 0..1 条记忆候选（单行动单记忆）。"""
    policy = get_settings().action_memory_policy()
    row = policy.get(record.action_type)
    if row is None or not row.get("deposit"):
        return []
    memory_type = str(row.get("memory_type", "important_event"))
    importance = float(row.get("importance", 0.5))
    source = str(row.get("source", "user_derived"))

    if record.action_type == "create_reminder":
        content_text = str(record.params.get("content", ""))
        if any(keyword in content_text for keyword in REMINDER_BIRTHDAY_KEYWORDS):
            memory_type = "user_fact"
            importance = 0.8
    if record.action_type == "cancel_reminder":
        content_text = str(record.params.get("target", ""))
    content = _template(record.action_type, record.params)
    if not content:
        return []
    if record.status == "failed":
        content = f"上次没能帮用户完成：{content}"
        importance = max(importance, 0.6)
        memory_type = "important_event"
    return [
        MemoryCandidate(
            action="save",
            type=memory_type,
            content=content[:120],
            importance=importance,
            confidence=0.8,
            source=source,
        )
    ]


def has_memory_effect(record: ActionRecord) -> bool:
    """幂等：effects 中已登记 memory 效果则跳过重复投递。"""
    result = record.result or {}
    for effect in result.get("effects", []):
        if effect.get("kind") == "memory":
            return True
    return False


def deliver_action_memory(record: ActionRecord, user_id: str, character_id: str = "asuna") -> dict | None:
    """投递入口（第 9 步收尾）：门控 + 边界表 + R1~R8 + 落库。失败只 log。"""
    settings = get_settings()
    if not settings.action_memory_policy_enabled:
        return None
    try:
        if record.action_type == "remember_fact" and record.status == "succeeded":
            return None
        if has_memory_effect(record):
            return None
        if record.status not in ("succeeded", "failed"):
            return None
        if record.status == "failed" and record.gate_reason is not None:
            return None
        candidates = to_memory_candidates(record)
        if not candidates:
            return None
        report = memory_policy.apply_policy(candidates)
        saved = report.saved
        if not saved:
            return None
        candidate = saved[0]
        memory = memory_repository.create_memory(
            user_id,
            character_id,
            content=candidate.content or "",
            memory_type=candidate.type,
            importance=candidate.importance,
            confidence=candidate.confidence,
            source=candidate.source,
        )
        return {"memory_id": memory.id, "content": memory.content}
    except Exception:
        logger.exception("行动记忆投递失败（不回滚行动）")
        return None
