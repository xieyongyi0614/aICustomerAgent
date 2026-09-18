"""TOOL-003 单测共享构造：内存注册表、打桩能力、执行器工厂与设置替身。"""

import inspect
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable

from app.models.action import ActionSchema, CapabilityResult
from app.models.tool import PermissionProfile, ToolDefinition, ToolParameter, ToolSchema
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import CapabilityRegistry
from app.services.tool.executor import ToolExecutor
from app.services.tool.health import ToolHealthTracker
from app.services.tool.registry import ToolRegistry
from tests.v24.tool002_support import definition, parameter, schema

NOW = datetime(2026, 6, 1, 12, 0, 0)


def param(
    name: str,
    type_: str = "string",
    *,
    required: bool = False,
    description: str = "",
    enum: tuple[Any, ...] = (),
    format_: str = "",
    pattern: str = "",
    min_length: int | None = None,
    max_length: int | None = None,
    min_value: float | int | None = None,
    max_value: float | int | None = None,
    default: Any = None,
    sensitive: bool = False,
) -> ToolParameter:
    return ToolParameter(
        name=name,
        type=type_,
        required=required,
        description=description,
        enum=enum,
        format=format_,
        pattern=pattern,
        min_length=min_length,
        max_length=max_length,
        min=min_value,
        max=max_value,
        default=default,
        sensitive=sensitive,
    )


def tool_settings(**overrides: Any) -> SimpleNamespace:
    """执行器级设置替身：默认总闸 on、其余子闸 off、熔断参数取默认。"""
    values: dict[str, Any] = {
        "tool_system_enabled": True,
        "tool_permission_enabled": False,
        "tool_schema_validation_enabled": False,
        "tool_observation_enabled": False,
        "tool_breaker_threshold": 3,
        "tool_breaker_cooldown_seconds": 300,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def registry_with(*definitions: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    for item in definitions:
        registry.register(item)
    return registry


def notification_definition(**overrides: Any) -> ToolDefinition:
    """自定义声明：绑定真实存在的 (notification, send)，可注入敏感参数与语义校验器。"""
    payload: dict[str, Any] = {
        "id": "builtin.notification.send",
        "name": "发送通知",
        "description": "向已授权收件人发送通知",
        "namespace": "builtin",
        "capability": "notification",
        "action": "send",
        "input_schema": schema(
            parameter("content", required=True, description="通知正文"),
            parameter("recipient", description="收件人"),
        ),
        "permission": PermissionProfile(level="sensitive", scope=("self",)),
        "side_effects": ("send_external",),
        "idempotency": "keyed",
    }
    payload.update(overrides)
    return ToolDefinition(**payload)


def sensitive_definition(**overrides: Any) -> ToolDefinition:
    parameters = list(notification_definition().input_schema.parameters)
    parameters[1] = ToolParameter(name="recipient", type="string", sensitive=True)
    payload: dict[str, Any] = {
        "id": "builtin.notification.send",
        "input_schema": ToolSchema(parameters=parameters),
    }
    payload.update(overrides)
    return notification_definition(**payload)


class StubCapability:
    """打桩能力：记录每次调用的入参，按 behavior 产出结果。"""

    def __init__(
        self,
        name: str = "notification",
        action: str = "send",
        required: list[str] | None = None,
        behavior: Callable[[dict, Any], Any] | None = None,
    ) -> None:
        self.name = name
        self.description = "打桩能力"
        self.actions = {action: ActionSchema(required=list(required or ["content"]))}
        self.action = action
        self.calls: list[dict] = []
        self._behavior = behavior or (
            lambda params, ctx: CapabilityResult(
                status="succeeded", payload={"message_id": "m-1"}
            )
        )

    def validate(self, action: str, params: dict) -> list[str]:
        return []

    async def execute(self, action: str, params: dict, ctx):
        self.calls.append(dict(params))
        result = self._behavior(params, ctx)
        if inspect.isawaitable(result):
            result = await result
        return result


def stub_registry(*capabilities: StubCapability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capability in capabilities:
        registry.register(capability)
    return registry


def build_executor(
    registry: ToolRegistry,
    capability: StubCapability,
    settings=None,
    timeout_seconds: float = 2.0,
    **kwargs: Any,
) -> ToolExecutor:
    """执行器工厂：能力侧走打桩注册表，工具侧走传入的工具注册表。"""
    resolved = settings if settings is not None else tool_settings()
    return ToolExecutor(
        registry,
        CapabilityExecutor(stub_registry(capability), timeout_seconds),
        settings=resolved,
        **kwargs,
    )


def tracker(registry: ToolRegistry, settings=None, clock=None) -> ToolHealthTracker:
    return ToolHealthTracker(registry, settings if settings is not None else tool_settings(), clock=clock)


__all__ = [
    "NOW",
    "StubCapability",
    "build_executor",
    "definition",
    "notification_definition",
    "param",
    "parameter",
    "registry_with",
    "schema",
    "sensitive_definition",
    "stub_registry",
    "tool_settings",
    "tracker",
]
