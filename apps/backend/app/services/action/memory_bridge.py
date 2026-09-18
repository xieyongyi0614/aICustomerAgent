"""V9 Action Memory Bridge（memory-policy.md §2~§4，V9-007）。

行动记忆第四供给方：候选经既有 memory_policy R1~R8 校验（零豁免）后由
memory_repository 落库；source 只用 user_stated / user_derived。

V2.4.0 TOOL-008：新增 `deliver` 泛化路径（键从 action_type 升级为 memory_policy_key），
工具记忆投递走泛化键（工具记忆子闸已随 V2.4.0 转正删除，不再回退 `deliver_action_memory`）。
两条路径共用同一政策闸与落库入口，幂等标记同为 `effects.kind == "memory"`。
"""

import logging

from app.character.asuna.action import (
    ACTION_MEMORY_TEMPLATES,
    REMINDER_BIRTHDAY_KEYWORDS,
)
from app.core.settings import get_settings
from app.models.action import ActionRecord
from app.models.memory import MemoryCandidate
from app.models.tool import ToolDefinition
from app.repositories import memory_repository
from app.services import memory_policy
from app.services.tool import memory_policy as tool_memory_policy
from app.services.tool.registry import get_tool_registry

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
    """幂等：effects 中已登记 memory 效果则跳过重复投递（TOOL-008 泛化后归口工具记忆策略）。"""
    return tool_memory_policy.has_memory_effect(record)


def _tool_definition(record: ActionRecord) -> ToolDefinition | None:
    """工具声明（供硬纪律①读 `side_effects` 与命名空间判定）；无注册表或不注册返回 None。"""
    tool_id = tool_memory_policy.tool_id_of(record)
    registry = get_tool_registry()
    if tool_id is None or registry is None:
        return None
    return registry.get(tool_id)


def deliver(record: ActionRecord, user_id: str, character_id: str = "asuna") -> dict | None:
    """工具结果记忆投递（TOOL-008 §4.2）：门控 + 幂等 + 分类 + R1~R8 + 落库。

    工具记忆子闸已随 V2.4.0 转正删除（不再回退 `deliver_action_memory`）；
    政策总开关 off → 不投递。任何异常只 log，**不回滚工具执行**（V9 既有纪律）。
    """
    settings = get_settings()
    if not settings.action_memory_policy_enabled:
        return None
    try:
        if tool_memory_policy.has_memory_effect(record):
            return None
        definition = _tool_definition(record)
        candidates = tool_memory_policy.get_tool_memory_policy().to_candidates(
            record, definition
        )
        if not candidates:
            decision = tool_memory_policy.get_tool_memory_policy().classify(
                record, definition
            )
            logger.debug(
                "工具结果未产生记忆候选: tool_id=%s reason=%s",
                tool_memory_policy.policy_key_for(record, definition),
                decision.reason,
            )
            return None
        report = memory_policy.apply_policy(candidates)
        saved = report.saved
        if not saved:
            logger.info(
                "工具结果记忆候选未通过政策闸，已丢弃: tool_id=%s rules=%s",
                tool_memory_policy.policy_key_for(record, definition),
                [outcome.rule for outcome in report.discarded],
            )
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
        logger.exception("工具结果记忆投递失败（不回滚工具执行）")
        return None


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
