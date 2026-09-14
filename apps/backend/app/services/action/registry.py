"""V9 CapabilityRegistry（capability-system.md §2~§3）。

能力是手脚不是逻辑：能力只知道"怎么做"；调度权、重试决策、回复生成都不在能力里。
Registry 模块级单例、运行期不增删（代码注册而非热插拔）。
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


def get_capability_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        from app.services.action.capabilities import register_builtin

        _registry = CapabilityRegistry()
        register_builtin(_registry)
    return _registry
