"""TOOL-008 单测共享构造：行动记录（含工具步骤）、工具声明与记忆计数。"""

from typing import Any

from app.models.action import ActionRecord
from app.models.tool import (
    PermissionProfile,
    ToolDefinition,
    ToolParameter,
    ToolSchema,
)
from app.repositories import memory_repository

USER = "u-tool008"
OTHER_USER = "u-tool008-other"
CHARACTER = "asuna"

ACTION_TYPE_BY_TOOL_ID: dict[str, str] = {
    "builtin.reminder.create": "create_reminder",
    "builtin.reminder.cancel": "cancel_reminder",
    "builtin.memory.save": "remember_fact",
    "world.object.create": "create_object",
    "world.object.move": "move_object",
    "world.object.use": "use_object",
    "world.env.query": "query_environment",
    "builtin.search.query": "query_search",
    "builtin.notification.send": "send_notification",
    "channel.feishu.send": "send_notification",
}

NAMESPACE_BY_TOOL_ID: dict[str, str] = {
    "builtin.reminder.create": "builtin",
    "builtin.reminder.cancel": "builtin",
    "builtin.memory.save": "builtin",
    "world.object.create": "world",
    "world.object.move": "world",
    "world.object.use": "world",
    "world.env.query": "world",
    "builtin.search.query": "builtin",
    "builtin.notification.send": "builtin",
    "channel.feishu.send": "channel",
}

PERMISSION_LEVEL_BY_NAMESPACE: dict[str, str] = {
    "builtin": "normal",
    "world": "normal",
    "channel": "sensitive",
    "ext.api": "sensitive",
    "user": "dangerous",
}

SIDE_EFFECTS_BY_TOOL_ID: dict[str, tuple[str, ...]] = {
    "builtin.reminder.create": ("write_world",),
    "builtin.reminder.cancel": ("write_world",),
    "builtin.memory.save": ("write_memory",),
    "world.object.create": ("write_world",),
    "world.object.move": ("write_world",),
    "world.object.use": ("write_world",),
    "world.env.query": ("read",),
    "builtin.search.query": ("read",),
    "builtin.notification.send": ("send_external",),
    "channel.feishu.send": ("send_external",),
}


def tool_definition(
    tool_id: str,
    *,
    namespace: str | None = None,
    side_effects: tuple[str, ...] | None = None,
    memory_policy_key: str | None = None,
    permission_level: str | None = None,
) -> ToolDefinition:
    """按工具 id 派生声明（不经注册表，便于硬纪律负例直接注入配置）。"""
    resolved_namespace = namespace or NAMESPACE_BY_TOOL_ID.get(
        tool_id, tool_id.split(".")[0]
    )
    return ToolDefinition(
        id=tool_id,
        name="工具",
        description="单测声明",
        namespace=resolved_namespace,
        capability="reminder",
        action="create",
        input_schema=ToolSchema(
            parameters=[ToolParameter(name="content", type="string")]
        ),
        permission=PermissionProfile(
            level=permission_level
            or PERMISSION_LEVEL_BY_NAMESPACE.get(resolved_namespace, "normal"),
            scope=("self",),
        ),
        side_effects=(
            SIDE_EFFECTS_BY_TOOL_ID.get(tool_id, ()) if side_effects is None else side_effects
        ),
        memory_policy_key=memory_policy_key,
    )


def tool_step(
    tool_id: str,
    params: dict[str, Any] | None = None,
    *,
    status: str = "succeeded",
    failure_kind: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "effects": []}
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return {
        "index": 0,
        "capability": tool_id.split(".")[0],
        "action": "run",
        "params": dict(params or {}),
        "status": "succeeded" if status == "succeeded" else "failed",
        "result": result,
        "tool_id": tool_id,
        "permission": {},
        "validation": None,
        "duration_ms": 1,
    }


def record(
    tool_id: str | None = None,
    *,
    params: dict[str, Any] | None = None,
    status: str = "succeeded",
    action_type: str | None = None,
    gate_reason: str | None = None,
    failure_kind: str | None = None,
    user_id: str = USER,
    character_id: str = CHARACTER,
    attempt: int = 1,
    result: dict[str, Any] | None = None,
    record_id: str = "act-tool008",
) -> ActionRecord:
    """行动记录：`steps[].tool_id` 携带工具身份（工具路径由 TOOL-003 写入）。"""
    payload = dict(params or {})
    steps = (
        []
        if tool_id is None
        else [tool_step(tool_id, payload, status=status, failure_kind=failure_kind)]
    )
    return ActionRecord(
        id=record_id,
        user_id=user_id,
        character_id=character_id,
        action_type=action_type or ACTION_TYPE_BY_TOOL_ID.get(tool_id or "", "create_reminder"),
        params=payload,
        status=status,
        gate_reason=gate_reason,
        steps=steps,
        attempt=attempt,
        result=result,
    )


def memory_contents(user_id: str = USER) -> list[str]:
    return [memory.content for memory in memory_repository.list_by_user(user_id, limit=200)]


def memory_count(user_id: str = USER) -> int:
    return len(memory_contents(user_id))


__all__ = [
    "CHARACTER",
    "OTHER_USER",
    "USER",
    "memory_contents",
    "memory_count",
    "record",
    "tool_definition",
    "tool_step",
]
