"""TOOL-005 单测共享构造：四档工具声明、快照、设置替身与确认流夹具。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.core import timeutil
from app.models.action import ActionIntent, make_dedupe_key
from app.models.tool import PermissionProfile, ToolDefinition, ToolSchema
from app.services.tool.permission import PermissionSnapshot
from tests.v24.tool002_support import parameter, schema
from tests.v24.tool003_support import NOW, StubCapability

SAFE_TOOL_ID = "world.env.query"
NORMAL_TOOL_ID = "builtin.reminder.create"
SENSITIVE_TOOL_ID = "builtin.notification.send"
CHANNEL_TOOL_ID = "channel.feishu.send"
DANGEROUS_TOOL_ID = "builtin.memory.purge"
UNTRUSTED_TOOL_ID = "user.notes.delete"
EXT_TOOL_ID = "ext.api.push.write"
CHANNEL_BASE_TOOL_ID = "channel.feishu.read"

CHANNEL_TOOL_SCOPE = ("channel:feishu",)
CHANNEL_BASE_SCOPE = ("channel:feishu.base",)
EXT_SCOPE = ("external:api.example.com",)


def permission_settings(**overrides: Any) -> SimpleNamespace:
    """权限闸设置替身：双闸默认 on，TTL 24 小时、复用开、白名单空。"""
    values: dict[str, Any] = {
        "tool_confirm_timeout_hours": 24,
        "tool_confirm_ttl_reuse": True,
        "tool_ext_allowed_hosts": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def safe_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": SAFE_TOOL_ID,
        "name": "查询环境状态",
        "description": "只读环境查询",
        "namespace": "world",
        "capability": "environment_query",
        "action": "query",
        "input_schema": ToolSchema(),
        "permission": PermissionProfile(
            level="safe", scope=("world",), override_reason="只读工具降级到命名空间下限之下"
        ),
        "side_effects": ("read",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def normal_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": NORMAL_TOOL_ID,
        "name": "创建提醒",
        "description": "创建一条提醒",
        "namespace": "builtin",
        "capability": "reminder",
        "action": "create",
        "input_schema": ToolSchema(
            parameters=[
                parameter("content", required=True),
                parameter("due_at", required=True),
            ]
        ),
        "permission": PermissionProfile(level="normal", scope=("world",)),
        "side_effects": ("write_world",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def sensitive_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": SENSITIVE_TOOL_ID,
        "name": "发送通知",
        "description": "向用户发送一条通知",
        "namespace": "builtin",
        "capability": "notification",
        "action": "send",
        "input_schema": ToolSchema(parameters=[parameter("content", required=True)]),
        "permission": PermissionProfile(
            level="sensitive", scope=("self",), confirm="first_time"
        ),
        "side_effects": ("send_external",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def always_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": DANGEROUS_TOOL_ID,
        "name": "批量删除记忆",
        "description": "不可逆的批量删除",
        "namespace": "builtin",
        "capability": "memory",
        "action": "save",
        "input_schema": ToolSchema(parameters=[parameter("fact", required=True)]),
        "permission": PermissionProfile(
            level="dangerous", scope=("memory",), confirm="always"
        ),
        "side_effects": ("irreversible",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def channel_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": CHANNEL_TOOL_ID,
        "name": "飞书通道发送",
        "description": "经飞书通道发送消息",
        "namespace": "channel",
        "capability": "notification",
        "action": "send",
        "input_schema": ToolSchema(parameters=[parameter("content", required=True)]),
        "permission": PermissionProfile(
            level="sensitive", scope=CHANNEL_TOOL_SCOPE, confirm="first_time"
        ),
        "side_effects": ("send_external",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def channel_base_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": CHANNEL_BASE_TOOL_ID,
        "name": "飞书通道读取",
        "description": "读取通道基础信息",
        "namespace": "channel",
        "capability": "notification",
        "action": "send",
        "input_schema": ToolSchema(parameters=[parameter("content", required=True)]),
        "permission": PermissionProfile(
            level="sensitive", scope=CHANNEL_BASE_SCOPE, confirm="never"
        ),
        "side_effects": ("read",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def untrusted_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": UNTRUSTED_TOOL_ID,
        "name": "用户工具",
        "description": "用户自定义工具",
        "namespace": "user",
        "capability": "memory",
        "action": "save",
        "input_schema": ToolSchema(parameters=[parameter("fact", required=True)]),
        "permission": PermissionProfile(
            level="dangerous", scope=("notes",), confirm="always"
        ),
        "side_effects": ("irreversible",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def ext_definition(**overrides: Any) -> ToolDefinition:
    payload: dict[str, Any] = {
        "id": EXT_TOOL_ID,
        "name": "外部推送",
        "description": "向外部 API 推送数据",
        "namespace": "ext.api",
        "capability": "notification",
        "action": "send",
        "input_schema": ToolSchema(parameters=[parameter("content", required=True)]),
        "permission": PermissionProfile(
            level="sensitive", scope=EXT_SCOPE, confirm="first_time"
        ),
        "side_effects": ("send_external",),
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


ALL_LEVEL_DEFINITIONS = (
    safe_definition,
    normal_definition,
    sensitive_definition,
    always_definition,
)


def grant(
    tool_id: str,
    scope: tuple[str, ...] = (),
    *,
    expires_at: datetime | None = None,
    source: str = "user_confirm",
) -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "scope": list(scope),
        "granted_at": NOW,
        "expires_at": expires_at,
        "source": source,
    }


def snapshot(
    *,
    user_id: str = "u-1",
    now: datetime | None = None,
    grants: list[dict[str, Any]] | None = None,
    pending: list[dict[str, Any]] | None = None,
    channel_bound: bool = False,
    settings: Any = None,
    namespace_floors: dict[str, str] | None = None,
) -> PermissionSnapshot:
    return PermissionSnapshot(
        user_id=user_id,
        now=now or NOW,
        grants=list(grants or []),
        pending=list(pending or []),
        channel_bound=channel_bound,
        settings=settings if settings is not None else permission_settings(),
        namespace_floors=namespace_floors
        if namespace_floors is not None
        else {
            "builtin": "normal",
            "world": "normal",
            "channel": "sensitive",
            "ext.api": "sensitive",
            "user": "dangerous",
        },
    )


def intent(params: dict[str, Any] | None = None, action_type: str = "send_notification"):
    payload = dict(params or {})
    return ActionIntent(
        action_type=action_type,
        confidence="confident",
        params=payload,
        dedupe_key=make_dedupe_key(action_type, payload),
    )


def invocation(
    tool_id: str = SENSITIVE_TOOL_ID,
    params: dict[str, Any] | None = None,
    *,
    dedupe_key: str = "",
    action_type: str = "send_notification",
):
    from app.models.tool import ToolInvocation

    resolved = dict(params or {})
    return ToolInvocation(
        tool_id=tool_id,
        params=resolved,
        rationale="用户要求",
        source="conversation",
        intent=intent(resolved, action_type),
        dedupe_key=dedupe_key or make_dedupe_key(action_type, resolved),
    )


def notification_capability(behavior=None) -> StubCapability:
    return StubCapability(
        name="notification", action="send", required=["content"], behavior=behavior
    )


def expired_now() -> datetime:
    return timeutil.now() - timedelta(hours=48)


def future_now() -> datetime:
    return timeutil.now()


__all__ = [
    "ALL_LEVEL_DEFINITIONS",
    "CHANNEL_BASE_SCOPE",
    "CHANNEL_BASE_TOOL_ID",
    "CHANNEL_TOOL_ID",
    "CHANNEL_TOOL_SCOPE",
    "DANGEROUS_TOOL_ID",
    "EXT_SCOPE",
    "EXT_TOOL_ID",
    "NORMAL_TOOL_ID",
    "NOW",
    "SAFE_TOOL_ID",
    "SENSITIVE_TOOL_ID",
    "UNTRUSTED_TOOL_ID",
    "always_definition",
    "channel_base_definition",
    "channel_definition",
    "expired_now",
    "ext_definition",
    "future_now",
    "grant",
    "intent",
    "invocation",
    "normal_definition",
    "notification_capability",
    "permission_settings",
    "safe_definition",
    "sensitive_definition",
    "snapshot",
    "untrusted_definition",
]
