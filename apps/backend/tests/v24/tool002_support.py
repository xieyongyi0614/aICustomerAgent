"""TOOL-002 单测共享构造：ToolDefinition / ToolSchema 与预期映射表。"""

from typing import Any

from app.models.tool import (
    PermissionProfile,
    ToolDefinition,
    ToolParameter,
    ToolSchema,
)

BUILTIN_TOOL_IDS: tuple[str, ...] = (
    "builtin.ledger.query",
    "builtin.ledger.record",
    "builtin.ledger.revise",
    "builtin.memory.save",
    "builtin.notification.send",
    "builtin.reminder.cancel",
    "builtin.reminder.create",
    "builtin.search.query",
    "channel.feishu.send",
    "world.env.query",
    "world.object.create",
    "world.object.move",
    "world.object.use",
)

BUILTIN_ENABLED_IDS: tuple[str, ...] = tuple(
    tool_id for tool_id in BUILTIN_TOOL_IDS if tool_id != "channel.feishu.send"
)

MAPPING_TABLE: tuple[dict[str, Any], ...] = (
    {
        "tool_id": "builtin.reminder.create",
        "capability": "reminder",
        "action": "create",
        "namespace": "builtin",
        "level": "normal",
        "side_effects": ("write_world",),
        "idempotency": "keyed",
        "priority": 10,
    },
    {
        "tool_id": "builtin.reminder.cancel",
        "capability": "reminder",
        "action": "cancel",
        "namespace": "builtin",
        "level": "normal",
        "side_effects": ("write_world",),
        "idempotency": "keyed",
        "priority": 20,
    },
    {
        "tool_id": "builtin.memory.save",
        "capability": "memory",
        "action": "save",
        "namespace": "builtin",
        "level": "normal",
        "side_effects": ("write_memory",),
        "idempotency": "keyed",
        "priority": 30,
    },
    {
        "tool_id": "world.object.create",
        "capability": "world_action",
        "action": "create",
        "namespace": "world",
        "level": "normal",
        "side_effects": ("write_world",),
        "idempotency": "keyed",
        "priority": 40,
    },
    {
        "tool_id": "world.object.move",
        "capability": "world_action",
        "action": "move",
        "namespace": "world",
        "level": "normal",
        "side_effects": ("write_world",),
        "idempotency": "keyed",
        "priority": 50,
    },
    {
        "tool_id": "world.object.use",
        "capability": "world_action",
        "action": "use",
        "namespace": "world",
        "level": "normal",
        "side_effects": ("write_world",),
        "idempotency": "keyed",
        "priority": 60,
    },
    {
        "tool_id": "world.env.query",
        "capability": "environment_query",
        "action": "query",
        "namespace": "world",
        "level": "safe",
        "side_effects": ("read",),
        "idempotency": "natural",
        "priority": 70,
    },
    {
        "tool_id": "builtin.search.query",
        "capability": "search",
        "action": "query",
        "namespace": "builtin",
        "level": "safe",
        "side_effects": ("read",),
        "idempotency": "natural",
        "priority": 80,
    },
    {
        "tool_id": "builtin.notification.send",
        "capability": "notification",
        "action": "send",
        "namespace": "builtin",
        "level": "sensitive",
        "side_effects": ("send_external",),
        "idempotency": "keyed",
        "priority": 90,
    },
    {
        "tool_id": "channel.feishu.send",
        "capability": "channel_feishu",
        "action": "send",
        "namespace": "channel",
        "level": "sensitive",
        "side_effects": ("send_external",),
        "idempotency": "keyed",
        "priority": 100,
    },
    {
        "tool_id": "builtin.ledger.record",
        "capability": "ledger",
        "action": "record",
        "namespace": "builtin",
        "level": "normal",
        "side_effects": ("irreversible",),
        "idempotency": "keyed",
        "priority": 35,
    },
    {
        "tool_id": "builtin.ledger.revise",
        "capability": "ledger",
        "action": "revise",
        "namespace": "builtin",
        "level": "normal",
        "side_effects": ("irreversible",),
        "idempotency": "keyed",
        "priority": 36,
    },
    {
        "tool_id": "builtin.ledger.query",
        "capability": "ledger",
        "action": "query",
        "namespace": "builtin",
        "level": "safe",
        "side_effects": ("read",),
        "idempotency": "natural",
        "priority": 37,
    },
)


def parameter(
    name: str,
    type_: str = "string",
    *,
    required: bool = False,
    description: str = "",
    enum: tuple[Any, ...] = (),
) -> ToolParameter:
    return ToolParameter(
        name=name,
        type=type_,
        required=required,
        description=description,
        enum=enum,
    )


def schema(*parameters: ToolParameter) -> ToolSchema:
    return ToolSchema(parameters=list(parameters))


def reminder_create_schema() -> ToolSchema:
    return schema(
        parameter("content", required=True, description="提醒内容"),
        parameter("due_at", "datetime", required=True, description="触发时间"),
    )


def definition(**overrides: Any) -> ToolDefinition:
    """合法基线声明：builtin.reminder.create（经 TOOL-001 构造期校验）。"""
    payload: dict[str, Any] = {
        "id": "builtin.reminder.create",
        "name": "创建提醒",
        "description": "为用户创建一条提醒",
        "when_to_use": "用户要求在未来某个时间点提醒某事时使用",
        "namespace": "builtin",
        "capability": "reminder",
        "action": "create",
        "input_schema": reminder_create_schema(),
        "permission": PermissionProfile(level="normal", scope=("world",)),
        "side_effects": ("write_world",),
        "idempotency": "keyed",
        "priority": 10,
        "tags": ("reminder", "world"),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def raw_definition(**overrides: Any) -> ToolDefinition:
    """绕过 TOOL-001 构造期校验的声明，用于制造注册期校验负例。"""
    payload = {field: getattr(definition(), field) for field in ToolDefinition.model_fields}
    payload.update(overrides)
    return ToolDefinition.model_construct(**payload)
