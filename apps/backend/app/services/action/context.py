"""V9 Action Context（tool-integration.md §4，V9-006）。

装配与渲染行动上下文段：让角色知道"我做过什么、成败如何"。
纯函数渲染 + 有界查询，action_ctx=None 时 prompt 字节与 V8.5 完全一致。

V2.4.0 TOOL-005：待确认行动（`gate_reason=pending_confirmation`）的确认话术进入回复素材——
权限闸开启时该行动以小节形式传入角色语气确认话术（TOOL-005 §2.3 步骤③），关闭时渲染
与 V9 逐字节一致。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.character.asuna.tool import CONFIRM_PROMPT_MAX_CHARS
from app.core.settings import get_settings
from app.models.action import TERMINAL_STATUSES
from app.repositories import action_repository

logger = logging.getLogger(__name__)

GATE_REASON_PENDING_CONFIRMATION = "pending_confirmation"


@dataclass
class ActionItem:
    action_type: str
    status: str
    summary: str
    updated_at: datetime | None = None
    gate_reason: str | None = None
    attempt: int = 1
    record_id: str = ""


@dataclass
class ActionContext:
    items: list[ActionItem] = field(default_factory=list)


def _pending_confirmation_prompt(record) -> str | None:
    """待确认行动的确认话术（角色语气）；非待确认态返回 None。"""
    if getattr(record, "gate_reason", None) != GATE_REASON_PENDING_CONFIRMATION:
        return None
    result = record.result or {}
    text = " ".join(str(result.get("error") or "").split())
    return text[:CONFIRM_PROMPT_MAX_CHARS] or None


def _summarize_record(record) -> ActionItem:
    confirmation_prompt = _pending_confirmation_prompt(record)
    if confirmation_prompt is not None:
        return ActionItem(
            action_type=record.action_type,
            status=record.status,
            summary=confirmation_prompt,
            updated_at=record.updated_at,
            gate_reason=record.gate_reason,
            attempt=record.attempt,
            record_id=record.id,
        )
    params = record.params or {}
    action_type = record.action_type
    if action_type == "create_reminder":
        content = str(params.get("content", ""))[:30]
        summary = f"设提醒：{content}"
    elif action_type == "cancel_reminder":
        target = str(params.get("target", ""))[:30]
        summary = f"取消提醒：{target}"
    elif action_type == "remember_fact":
        fact = str(params.get("fact", ""))[:30]
        summary = f"记住：{fact}"
    elif action_type == "create_object":
        obj = str(params.get("object", ""))[:30]
        summary = f"准备：{obj}"
    elif action_type == "move_object":
        obj = str(params.get("object", ""))[:20]
        loc = str(params.get("location", ""))[:20]
        summary = f"移动{obj}到{loc}"
    elif action_type == "use_object":
        obj = str(params.get("object", ""))[:30]
        summary = f"使用：{obj}"
    elif action_type == "query_environment":
        dim = str(params.get("dimension", "环境"))
        summary = f"查询：{dim}"
    elif action_type == "query_search":
        query = str(params.get("query", ""))[:30]
        summary = f"搜索：{query}"
    elif action_type == "send_notification":
        summary = "发送通知"
    else:
        summary = action_type

    return ActionItem(
        action_type=action_type,
        status=record.status,
        summary=summary,
        updated_at=record.updated_at,
        gate_reason=record.gate_reason,
        attempt=record.attempt,
        record_id=record.id,
    )


def _status_label(item: ActionItem) -> str:
    if item.status == "succeeded":
        return "已完成"
    if item.status == "failed":
        return "失败"
    if item.status == "executing":
        if item.attempt > 1:
            return f"执行中（第{item.attempt}次）"
        return "执行中"
    if item.status == "planned":
        return "计划中"
    if item.status == "created":
        return "待执行"
    if item.status == "cancelled":
        return "已取消"
    return item.status


def build_action_context(user_id: str, session_id: str | None = None) -> ActionContext | None:
    settings = get_settings()
    if not settings.action_enabled:
        return None
    try:
        records = action_repository.list_records(user_id, limit=20)
        if not records:
            return None
        budget = settings.action_context_char_budget
        items: list[ActionItem] = []
        for record in records:
            items.append(_summarize_record(record))
        non_terminal = [i for i in items if i.status not in TERMINAL_STATUSES]
        terminal = [i for i in items if i.status in TERMINAL_STATUSES]
        terminal.sort(key=lambda i: i.updated_at or datetime.min, reverse=True)
        selected = non_terminal[:3] + terminal[:2]
        selected = selected[:5]
        return ActionContext(items=selected) if selected else None
    except Exception:
        logger.exception("行动上下文装配失败，降级 None")
        return None


def render_action_section(ctx: ActionContext | None, budget: int = 400) -> str:
    if ctx is None or not ctx.items:
        return ""
    lines: list[str] = ["【行动】"]
    for item in ctx.items:
        label = _status_label(item)
        if item.status == "cancelled":
            continue
        if item.status == "failed":
            reason = item.gate_reason or "执行失败"
            line = f"上次失败：{item.summary}——{reason}"
        elif item.status == "succeeded":
            line = f"{item.summary}（{label}）"
        else:
            line = f"进行中：{item.summary}（{label}）"
        candidate = "\n".join(lines + [line])
        if len(candidate) > budget:
            lines.append("…")
            break
        lines.append(line)
    result = "\n".join(lines)
    if len(result) > budget:
        result = result[: budget - 1] + "…"
    return result
