"""TOOL-004 单测共享构造：工具注册表、ToolContext、声明工厂与 IO 探针。"""

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from app.application.agent_runtime.models import (
    RUN_KIND_AUTONOMOUS_TICK,
    RUN_KIND_EVENT_DRIVEN,
    RUN_KIND_FOREGROUND_CHAT,
)
from app.models.tool import PermissionProfile, ToolDefinition, ToolSchema
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from tests.v24.tool002_support import parameter

NOW = datetime(2026, 9, 14, 21, 30, 0)


def tool_settings(**overrides: Any) -> SimpleNamespace:
    """工具面投影级设置替身：默认总闸 + 工具面子闸 on、上限 12、世界可用。"""
    values: dict[str, Any] = {
        "tool_surface_max_tools": 12,
        "action_plan_expires_minutes": 5,
        "action_execution_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def builtin_registry() -> ToolRegistry:
    """全量内置声明注册表（10 条，channel.feishu.send 为代码态 disabled）。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def notification_send_parameters() -> list:
    """(notification, send) 的必需参数声明（注册期 schema 自洽校验要求）。"""
    return [parameter("content", required=True)]


def surface_context(**overrides: Any) -> ToolContext:
    payload: dict[str, Any] = {
        "user_id": "u-surface",
        "now": NOW,
        "settings": tool_settings(),
        "run_kind": RUN_KIND_FOREGROUND_CHAT,
    }
    payload.update(overrides)
    return ToolContext(**payload)


def tool_definition(
    tool_id: str,
    *,
    namespace: str = "builtin",
    capability: str = "reminder",
    action: str = "create",
    tags: tuple[str, ...] = (),
    priority: int = 100,
    side_effects: tuple[str, ...] = ("write_world",),
    status: str = "enabled",
    level: str | None = None,
    parameters: list | None = None,
) -> ToolDefinition:
    """测试声明工厂（默认绑定 (reminder, create)，含其必需参数）。"""
    resolved_level = level or ("sensitive" if namespace == "channel" else "normal")
    scope = ("channel:feishu",) if namespace == "channel" else ("world",)
    return ToolDefinition(
        id=tool_id,
        name="测试工具",
        description="TOOL-004 单测声明",
        namespace=namespace,
        capability=capability,
        action=action,
        input_schema=ToolSchema(
            parameters=list(
                parameters
                if parameters is not None
                else [parameter("content", required=True), parameter("due_at", "datetime", required=True)]
            )
        ),
        permission=PermissionProfile(level=resolved_level, scope=scope),
        side_effects=side_effects,
        status=status,
        priority=priority,
        tags=tags,
    )


def registry_with(*definitions: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry


class IoProbe:
    """DB / 网络 / LLM 调用计数探针：任何一次触达都计入并把调用打死。"""

    def __init__(self) -> None:
        self.counts = {"db": 0, "net": 0, "llm": 0}

    def total(self) -> int:
        return sum(self.counts.values())

    def forbid_db(self, *args: Any, **kwargs: Any):
        self.counts["db"] += 1
        raise AssertionError("工具面投影不得触达数据库")

    def forbid_net(self, *args: Any, **kwargs: Any):
        self.counts["net"] += 1
        raise AssertionError("工具面投影不得触达网络")

    def forbid_llm(self, *args: Any, **kwargs: Any):
        self.counts["llm"] += 1
        raise AssertionError("工具面投影不得触达 LLM")


def install_io_probe(monkeypatch) -> IoProbe:
    """把 DB / socket / LLM 网关三个 IO 面替换为计数探针。"""
    import socket

    import app.core.db as db_module
    from app.application.agent_runtime import llm_gateway

    probe = IoProbe()
    monkeypatch.setattr(db_module, "SessionLocal", probe.forbid_db)
    monkeypatch.setattr(socket.socket, "connect", probe.forbid_net)
    monkeypatch.setattr(socket, "create_connection", probe.forbid_net)
    monkeypatch.setattr(llm_gateway, "acquire", probe.forbid_llm)
    return probe


__all__ = [
    "NOW",
    "RUN_KIND_AUTONOMOUS_TICK",
    "RUN_KIND_EVENT_DRIVEN",
    "RUN_KIND_FOREGROUND_CHAT",
    "builtin_registry",
    "install_io_probe",
    "notification_send_parameters",
    "registry_with",
    "surface_context",
    "tool_definition",
    "tool_settings",
]
