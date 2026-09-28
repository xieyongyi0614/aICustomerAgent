"""TOOL-006 单测共享构造：自治工具面夹具、工具事实注入与冻结面断言。"""

import asyncio
import re
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.character.asuna import PERSISTENT_GOALS
from app.character.asuna.tool import SurfaceRule
from app.core.db import Message
from app.models.tool import PermissionProfile, ToolDefinition, ToolSchema
from app.services import conversation_service
from app.services.tool.context import ToolContext
from app.services.tool.registry import ToolRegistry, register_builtin_tools
from app.services.tool.surface import ToolSurfaceResolver
from tests.v24.tool002_support import parameter

NOW = datetime(2026, 9, 14, 21, 30, 0)
LATE_NIGHT = NOW.replace(hour=1, minute=0)
USER = "u-tool006"
SESSION = "tool006-s1"


def autonomy_settings(**overrides: Any) -> SimpleNamespace:
    """自治工具面设置替身：默认总闸 + 工具面子闸 on、上限 12、世界与行动可用。"""
    values: dict[str, Any] = {
        "tool_surface_max_tools": 12,
        "tool_breaker_threshold": 3,
        "tool_breaker_cooldown_seconds": 300,
        "observability_step_extra_max_chars": 2000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def autonomy_context(**overrides: Any) -> ToolContext:
    """自治来源 ToolContext（default 世界事实维度留空 = TOOL-007 未装配）。"""
    payload: dict[str, Any] = {
        "user_id": USER,
        "now": NOW,
        "settings": autonomy_settings(),
        "run_kind": RUN_KIND_AUTONOMOUS_TICK,
        "source": "autonomy",
    }
    payload.update(overrides)
    return ToolContext(**payload)


def builtin_registry() -> ToolRegistry:
    """全量内置声明注册表（10 条，含代码态 disabled 的 channel.feishu.send）。"""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def registry_with(*definitions: ToolDefinition) -> ToolRegistry:
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry


def tool_definition(
    tool_id: str,
    *,
    namespace: str = "builtin",
    capability: str = "reminder",
    action: str = "create",
    tags: tuple[str, ...] = (),
    priority: int = 100,
    status: str = "enabled",
    side_effects: tuple[str, ...] = ("write_world",),
    parameters: list | None = None,
) -> ToolDefinition:
    """自治工具面测试声明工厂（默认绑定 (reminder, create) 并含其必需参数）。"""
    return ToolDefinition(
        id=tool_id,
        name="测试工具",
        description="TOOL-006 单测声明",
        namespace=namespace,
        capability=capability,
        action=action,
        input_schema=ToolSchema(
            parameters=list(
                parameters
                if parameters is not None
                else [
                    parameter("content", required=True),
                    parameter("due_at", "datetime", required=True),
                ]
            )
        ),
        permission=PermissionProfile(
            level="sensitive" if namespace == "channel" else "normal",
            scope=("channel:feishu",) if namespace == "channel" else ("world",),
        ),
        side_effects=side_effects,
        status=status,
        priority=priority,
        tags=tags,
    )


def surface_of(
    registry: ToolRegistry, ctx: ToolContext | None = None, run_kind: str = RUN_KIND_AUTONOMOUS_TICK
):
    return ToolSurfaceResolver(registry).resolve(run_kind, ctx or autonomy_context())


def autonomous_rule() -> SurfaceRule:
    from app.character.asuna.tool import SURFACE_RULES

    return SURFACE_RULES[RUN_KIND_AUTONOMOUS_TICK]


class RecordingTrace:
    """最小 trace 替身：只记录调用（探针用，不落库）。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def record(self, name: str, duration_ms: float, status: str = "ok", **extra: Any) -> None:
        self.calls.append({"name": name, "duration_ms": duration_ms, "status": status, **extra})

    def names(self) -> list[str]:
        return [call["name"] for call in self.calls]


def seed_tick_fixture(session_id: str = SESSION, *, age_minutes: int = 40) -> str:
    """自治 tick 前置：持久目标 + 一段已闲置的对话（对齐 tests.integration 既有范式）。"""
    from app.repositories import conversation_repository, goal_repository

    goal_repository.seed_goals(USER, PERSISTENT_GOALS)
    conversation_repository.get_or_create_conversation(session_id, USER)
    conversation_service.save_turn(session_id, "我去忙了", "好的，去吧，我等你回来")
    with conversation_repository.SessionLocal() as session:
        for row in session.query(Message).all():
            row.created_at = NOW - timedelta(minutes=age_minutes)
        session.commit()
    return session_id


async def await_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


def normalized_source(obj: Any) -> str:
    """归一化源码（折叠空白）——冻结面 diff 断言的比较基准。"""
    import inspect

    return re.sub(r"\s+", " ", inspect.getsource(obj)).strip()


def has_io_import(module: Any, names: tuple[str, ...]) -> bool:
    """模块是否直接导入指定 IO 名字（静态零 IO 断言的粗粒度探针）。"""
    import inspect

    source = inspect.getsource(module)
    return any(re.search(rf"\b{re.escape(name)}\b", source) for name in names)


__all__ = [
    "LATE_NIGHT",
    "NOW",
    "SESSION",
    "USER",
    "autonomy_context",
    "autonomy_settings",
    "autonomous_rule",
    "await_until",
    "builtin_registry",
    "normalized_source",
    "registry_with",
    "seed_tick_fixture",
    "surface_of",
    "tool_definition",
    "RecordingTrace",
]
