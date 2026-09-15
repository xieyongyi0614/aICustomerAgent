"""V9 CapabilityRegistry（capability-system.md §2~§3）。

能力是手脚不是逻辑：能力只知道"怎么做"；调度权、重试决策、回复生成都不在能力里。
Registry 模块级单例、运行期不增删（代码注册而非热插拔）；唯一例外是 TOOL-011 的自定义
工具注销，它经 `CapabilityRegistry.unregister`（正式方法，不触私有字典）解除登记，
且不触碰 V9 六能力。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.models.action import ActionSchema, CapabilityResult


@dataclass(frozen=True)
class ExecutionContext:
    """能力只拿到执行上下文，拿不到对话与 prompt。

    `dedupe_key`（V2.4.0 TOOL-010 追加，默认空）：行动台账的幂等键，工具执行器在调用
    实现体前从 `ToolInvocation.dedupe_key` 填入，供"外发类"能力直填
    `OutboundMessage.idempotency_key`（§7.6 幂等天然对齐）。V9 六能力不读该字段，
    行为逐字节不变。
    """

    user_id: str
    character_id: str = "asuna"
    record_id: str = ""
    now: datetime | None = None
    settings: Any = None
    dedupe_key: str = ""


class Capability(Protocol):
    name: str
    description: str
    actions: dict[str, ActionSchema]

    def validate(self, action: str, params: dict) -> list[str]: ...

    async def execute(self, action: str, params: dict, ctx: ExecutionContext) -> CapabilityResult: ...


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._capabilities:
            raise ValueError(f"能力重复注册: {capability.name}")
        self._capabilities[capability.name] = capability

    def unregister(self, name: str) -> bool:
        """移除已登记的能力（V2.4.0 TOOL-011 自定义工具注销的写入面）。

        语义与边界：
        - 按能力名精确匹配，**未注册返回 False**（幂等，不抛错）；
        - 只影响本实例；模块级单例（`get_capability_registry`）的内置六能力与通道能力
          不在运行期被移除，故对 V9 行为零影响；
        - 移除后 `get` / `has` 立即返回 `None` / `False`，已在执行的调用方不受影响
          （能力对象本身不销毁，只解除登记）；
        - 调用方只有 `services/tool/user_defined.py`（自定义工具注销）。
        """
        return self._capabilities.pop(name, None) is not None

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def has(self, name: str, action: str | None = None) -> bool:
        capability = self._capabilities.get(name)
        if capability is None:
            return False
        if action is None:
            return True
        return action in capability.actions

    def describe(self) -> list[dict]:
        return [
            {
                "name": capability.name,
                "description": capability.description,
                "actions": {
                    action: {"required": schema.required, "optional": schema.optional}
                    for action, schema in capability.actions.items()
                },
            }
            for capability in self._capabilities.values()
        ]


_registry: CapabilityRegistry | None = None

_registry_flags: dict[str, bool] = {}

REGISTRY_FLAG_NAMES: tuple[str, ...] = (
    "v24_tool_system_enabled",
    "v24_tool_channel_enabled",
    "feishu_enabled",
    "v24_tool_external_api_enabled",
)


def get_capability_registry() -> CapabilityRegistry:
    """模块级单例：首次调用时构建一次，**注册表内容 = 首次构建时的 flag 快照，进程内冻结**。

    条件注册（`register_builtin`：`channel_feishu` 需通道可用、`external_api` 需外部面双闸）
    只读构建那一刻的开关状态；此后即使开关翻转也不会重建，追加注册需先清 `_registry`
    （测试夹具的手法）或重启进程。构建期快照经 `capability_registry_flags()` 只读暴露，
    用于排查"为何某能力未注册"。
    """
    global _registry
    if _registry is None:
        from app.core.settings import get_settings
        from app.services.action.capabilities import register_builtin

        settings = get_settings()
        _registry = CapabilityRegistry()
        register_builtin(_registry)
        _registry_flags.clear()
        _registry_flags.update(
            {name: bool(getattr(settings, name, False)) for name in REGISTRY_FLAG_NAMES}
        )
    return _registry


def capability_registry_flags() -> dict[str, bool]:
    """能力注册表的**构建期** flag 快照（只读副本）；未构建过则返回空字典。"""
    return dict(_registry_flags)


def peek_capability_registry() -> CapabilityRegistry | None:
    """已构建的能力注册表单例（只读、**不触发构建**）；未构建返回 `None`。

    排障读面专用：GET 类端点不应因读一次状态而把注册表按当前 Flag 就地建起来。
    """
    return _registry
