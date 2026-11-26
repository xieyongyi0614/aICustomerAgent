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
    ActionResult,
    ActionStep,
    CapabilityResult,
    ExecutionKind,
)
from app.services.action.registry import CapabilityRegistry, ExecutionContext
from app.services.action import result as result_service

logger = logging.getLogger(__name__)


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


def step_result_payload(result: ActionResult) -> dict[str, Any]:
    """steps[].result 全形态：新契约 + 旧读键 payload（outbox / 证据窗依赖）。"""
    dumped = result.dual_write_legacy_keys()
    payload = dict(result.output or {})
    if result.failure_kind is not None:
        payload.setdefault("failure_kind", result.failure_kind)
    dumped["payload"] = payload
    return dumped


def step_extras_from_result(result: ActionResult) -> dict[str, Any]:
    meta = result.metadata or {}
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    duration = (
        meta.get("duration_ms")
        or (usage.get("duration_ms") if usage else 0)
        or 0
    )
    return {
        "tool_id": meta.get("tool_id"),
        "permission": meta.get("permission") or {},
        "validation": meta.get("validation"),
        "duration_ms": int(duration),
    }


class ActionExecutor:
    """统一执行面：接收 Action → 选执行方式 → 执行 → 捕获异常 → 返回 ActionResult。"""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        timeout_seconds: float = 10.0,
        tool_executor: Any = None,
        tool_resolver: Any = None,
        permission_snapshot: Any = None,
        tool_context: Any = None,
    ):
        self.capability_executor = CapabilityExecutor(registry, timeout_seconds)
        self.tool_executor = tool_executor
        self.tool_resolver = tool_resolver
        self.permission_snapshot = permission_snapshot
        self.tool_context = tool_context

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
        return result_service.from_capability_result(result, action_id=action.id)

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
        exec_ctx = ctx
        if self.tool_context is not None:
            exec_ctx = self.tool_context
        run_kwargs: dict[str, Any] = {}
        if self.permission_snapshot is not None:
            run_kwargs["permission_snapshot"] = self.permission_snapshot
        execution = await self.tool_executor.run(
            binding,
            invocation,
            exec_ctx,
            **run_kwargs,
        )
        return result_service.from_tool_execution(execution, action_id=action.id)

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
            # 工具绑定优先（v26 去门控裁决 B）：凡能解析出工具绑定的动作一律经
            # 工具五段执行（权限/确认/校验/归一/健康），解析不出绑定才按分派落位。
            if self.tool_executor is not None and self.tool_resolver is not None:
                try:
                    binding, invocation = self.tool_resolver(action)
                except Exception:
                    logger.exception("工具绑定解析异常，回退分派路径 action_id=%s", action.id)
                    binding = invocation = None
                if binding is not None and invocation is not None:
                    return await self.execute_tool(action, ctx)
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
