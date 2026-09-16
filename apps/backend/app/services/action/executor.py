"""V9 CapabilityExecutor + V2.6.0 ActionExecutor 分派层（execution-engine.md §2）。

CapabilityExecutor：超时包裹 wait_for、异常归一、usage 统计；重试决策在 ActionEngine。
ActionExecutor：按 ACTION_EXECUTION_MAP 分派 Internal / Tool / External，不决策、不重试。
"""

import asyncio
import logging
import time
from typing import Any

from app.character.asuna.action import ACTION_CAPABILITY_MAP
from app.models.action import (
    ACTION_EXECUTION_MAP,
    Action,
    ActionEffect,
    ActionResult,
    ActionStep,
    CapabilityResult,
    ExecutionKind,
)
from app.services.action.registry import CapabilityRegistry, ExecutionContext

logger = logging.getLogger(__name__)

_ERROR_MAP: dict[str, tuple[str, str]] = {
    "timeout": ("failed", "timeout"),
    "unavailable": ("failed", "unavailable"),
    "permanent": ("failed", "permanent"),
    "denied": ("failed", "permanent"),
    "invalid": ("failed", "permanent"),
}


class CapabilityExecutor:
    def __init__(self, registry: CapabilityRegistry, timeout_seconds: float):
        self.registry = registry
        self.timeout_seconds = timeout_seconds

    async def run(self, step: ActionStep, ctx: ExecutionContext) -> CapabilityResult:
        capability = self.registry.get(step.capability)
        if capability is None:
            return CapabilityResult(status="failed", error=f"能力未注册: {step.capability}", payload={"failure_kind": "permanent"})
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                capability.execute(step.action, step.params, ctx),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            result = CapabilityResult(
                status="timeout",
                error=f"能力执行超时（>{self.timeout_seconds}s）",
                payload={"failure_kind": "timeout"},
            )
        except Exception as exc:
            logger.exception("能力执行异常，归一为 failed")
            result = CapabilityResult(
                status="failed",
                error=f"{exc.__class__.__name__}: {exc}"[:80],
                payload={"failure_kind": "transient"},
            )
        duration_ms = (time.perf_counter() - started) * 1000
        usage = dict(result.usage)
        usage["duration_ms"] = round(duration_ms, 2)
        result.usage = usage
        return result


def dispatch(action: Action) -> ExecutionKind | None:
    return ACTION_EXECUTION_MAP.get(action.type)


def _normalize_capability_result(
    result: CapabilityResult, *, action_id: str
) -> ActionResult:
    failure_kind = None
    if result.payload:
        failure_kind = result.payload.get("failure_kind")
    if result.status == "succeeded":
        effects: list[ActionEffect] = []
        raw_effects = (result.payload or {}).get("effects") or []
        for item in raw_effects:
            if isinstance(item, dict):
                effects.append(
                    ActionEffect(
                        kind=item.get("kind", "note"),
                        ref=str(item.get("ref", "")),
                        detail=str(item.get("detail", "")),
                    )
                )
        return ActionResult(status="succeeded", effects=effects)
    if result.status == "timeout":
        return ActionResult(
            status="failed",
            error=result.error,
            failure_kind="timeout",
        )
    if result.status == "unavailable":
        return ActionResult(
            status="failed",
            error=result.error,
            failure_kind="unavailable",
        )
    return ActionResult(
        status="failed",
        error=result.error,
        failure_kind=failure_kind or "transient",
    )


def _tool_execution_to_result(execution: Any, *, action_id: str) -> ActionResult:
    status = getattr(execution, "status", "failed")
    error = getattr(execution, "error", None)
    if status == "succeeded":
        return ActionResult(status="succeeded", effects=[])
    mapped = _ERROR_MAP.get(status, ("failed", "transient"))
    return ActionResult(
        status=mapped[0],
        error=str(error)[:120] if error else status,
        failure_kind=mapped[1],
    )


class ActionExecutor:
    """统一执行面：接收 Action → 选执行方式 → 执行 → 捕获异常 → 返回 ActionResult。"""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        timeout_seconds: float = 10.0,
        tool_executor: Any = None,
        tool_resolver: Any = None,
    ):
        self.capability_executor = CapabilityExecutor(registry, timeout_seconds)
        self.tool_executor = tool_executor
        self.tool_resolver = tool_resolver

    def dispatch(self, action: Action) -> ExecutionKind | None:
        return dispatch(action)

    async def execute_internal(
        self, action: Action, ctx: ExecutionContext
    ) -> ActionResult:
        mapping = ACTION_CAPABILITY_MAP.get(action.type)
        if mapping is None:
            return ActionResult(
                status="failed",
                error=f"未知 Action Type: {action.type}",
                failure_kind="permanent",
            )
        capability_name, capability_action = mapping
        step = ActionStep(
            index=0,
            capability=capability_name,
            action=capability_action,
            params=dict(action.parameters or {}),
        )
        result = await self.capability_executor.run(step, ctx)
        return _normalize_capability_result(result, action_id=action.id)

    async def execute_tool(
        self, action: Action, ctx: ExecutionContext
    ) -> ActionResult:
        if self.tool_executor is None or self.tool_resolver is None:
            return ActionResult(
                status="failed",
                error="tool_executor_unavailable",
                failure_kind="unavailable",
            )
        binding, invocation = self.tool_resolver(action)
        if binding is None or invocation is None:
            return ActionResult(
                status="failed",
                error="tool_binding_unavailable",
                failure_kind="unavailable",
            )
        execution = await self.tool_executor.run(binding, invocation, ctx)
        return _tool_execution_to_result(execution, action_id=action.id)

    async def execute_external(
        self, action: Action, ctx: ExecutionContext
    ) -> ActionResult:
        return ActionResult(
            status="failed",
            error="external_adapter_reserved",
            failure_kind="unavailable",
        )

    async def run(self, action: Action, ctx: ExecutionContext) -> ActionResult:
        try:
            kind = self.dispatch(action)
            if kind is None:
                return ActionResult(
                    status="failed",
                    error=f"no_execution_map: {action.type}",
                    failure_kind="permanent",
                )
            if kind == "internal":
                return await self.execute_internal(action, ctx)
            if kind == "tool":
                return await self.execute_tool(action, ctx)
            return await self.execute_external(action, ctx)
        except Exception as exc:
            logger.exception("ActionExecutor.run 异常归一 action_id=%s", action.id)
            return ActionResult(
                status="failed",
                error=f"{exc.__class__.__name__}: {exc}"[:120],
                failure_kind="transient",
            )
