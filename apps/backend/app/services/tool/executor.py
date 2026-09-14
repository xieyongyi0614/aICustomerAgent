"""V2.4.0 ToolExecutor（architecture.md §4.3 / TOOL-003 §2.3、§4.1、§4.2）。

给"调用一个工具"装上四道纪律——授权、校验、超时、归一，五段固定短路：

```text
① resolve    注册表无此 tool_id / effective_status != enabled → unavailable，终止
② permission 权限闸 off → 占位 allow；deny → denied；confirm_required → pending_confirmation
③ validate   校验闸 off → 跳过；失败 → invalid；通过 → params := normalized
④ invoke     CapabilityExecutor.run(step, ctx)   ← V9 既有：超时 / 异常归一 / usage 计时
⑤ normalize  归一为 ToolResult + health 记一次 outcome
```

红线：**复用 V9 执行器调用实现，不复制其代码**（本模块不出现任何超时包裹与异常归一的
自研实现）；前置段失败路径零外部调用（不触达能力、不落台账——落库由 action_engine 负责）；
除编程错误（binding 与 invocation 的 tool_id 不一致）外，一切失败归一为 `ToolExecution.status`。

权限段为**占位实现（allow-all）**：接口形状已冻结，真实七步判定由 TOOL-005 替换。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.settings import get_settings
from app.models.action import ActionStep, CapabilityResult
from app.models.tool import (
    PermissionLevel,
    ToolBinding,
    ToolDefinition,
    ToolExecution,
    ToolInvocation,
    ToolResult,
)
from app.services.action.executor import CapabilityExecutor
from app.services.action.registry import ExecutionContext
from app.services.tool.context import ToolContext
from app.services.tool.health import ToolHealthTracker
from app.services.tool.normalizer import (
    ExecutionMeta,
    ObservationNormalizer,
    persisted_result,
    redact_params,
    redacted_param_names,
)
from app.services.tool.registry import ToolRegistry
from app.services.tool.validator import ParamValidator

logger = logging.getLogger(__name__)

PERMISSION_LAYER_OFF_REASON = "permission_layer_off"
PERMISSION_PLACEHOLDER_REASON = "permission_gate_placeholder_allow_all"

PERMISSION_ALLOW = "allow"
PERMISSION_DENY = "deny"
PERMISSION_CONFIRM_REQUIRED = "confirm_required"

PERMISSION_DECISIONS: tuple[str, ...] = (
    PERMISSION_ALLOW,
    PERMISSION_CONFIRM_REQUIRED,
    PERMISSION_DENY,
)

_TERMINAL_ERRORS: dict[str, str] = {
    "unavailable": "工具不可用（未注册 / 已禁用 / 已熔断）",
    "denied": "权限拒绝",
    "invalid": "参数校验未通过",
    "pending_confirmation": "等待用户确认",
}


@dataclass(frozen=True)
class PermissionSnapshot:
    """授权快照（纯数据）：本轮执行前预读，闸门内零 IO。TOOL-005 填充 grants/confirmed。"""

    user_id: str = ""
    character_id: str = "asuna"
    grants: tuple[str, ...] = ()
    confirmed: tuple[str, ...] = ()


@dataclass(frozen=True)
class PermissionDecision:
    """权限裁决（architecture.md §4.2 冻结形状）。"""

    decision: str
    level: PermissionLevel
    reason: str
    confirm_prompt: str | None = None
    scope_required: tuple[str, ...] = ()


class PermissionGate:
    """占位权限闸：权限闸 off 恒 allow；on 时仍为 allow-all（TOOL-005 替换实现）。"""

    def __init__(self, settings=None) -> None:
        self._settings = settings if settings is not None else get_settings()

    def evaluate(
        self,
        defn: ToolDefinition,
        inv: ToolInvocation,
        snapshot: PermissionSnapshot,
    ) -> PermissionDecision:
        scope = tuple(defn.permission.scope)
        if not getattr(self._settings, "v24_tool_permission_enabled", False):
            return PermissionDecision(
                decision=PERMISSION_ALLOW,
                level=defn.permission.level,
                reason=PERMISSION_LAYER_OFF_REASON,
                scope_required=scope,
            )
        logger.warning(
            "权限闸已开启但真实判定属 TOOL-005，占位实现放行：tool_id=%s", defn.id
        )
        return PermissionDecision(
            decision=PERMISSION_ALLOW,
            level=defn.permission.level,
            reason=PERMISSION_PLACEHOLDER_REASON,
            scope_required=scope,
        )


def resolve_step_binding(registry: ToolRegistry, step: ActionStep) -> ToolBinding | None:
    """按 (capability, action) 解析步骤绑定：可用者优先，同优先取 priority → tool_id 字典序。

    熔断 / 禁用的工具仍会被解析出来，由执行器 ① resolve 段判 `unavailable`
    （TOOL-004 将改为计划直接携带 tool_id）。
    """
    candidates = [
        definition
        for definition in registry.list(capability=step.capability)
        if definition.action == step.action
    ]
    if not candidates:
        return None
    ordered = sorted(
        candidates,
        key=lambda definition: (
            registry.effective_status(definition.id) != "enabled",
            definition.priority,
            definition.id,
        ),
    )
    return registry.resolve(ordered[0].id)


class ToolExecutor:
    """五段短路执行器；`run()` 不抛业务异常，只抛编程错误。"""

    def __init__(
        self,
        registry: ToolRegistry,
        capability_executor: CapabilityExecutor,
        *,
        settings=None,
        validator: ParamValidator | None = None,
        normalizer: ObservationNormalizer | None = None,
        health: ToolHealthTracker | None = None,
        permission_gate: PermissionGate | None = None,
    ) -> None:
        self.registry = registry
        self.capability_executor = capability_executor
        self.settings = settings if settings is not None else get_settings()
        self.validator = validator if validator is not None else ParamValidator()
        self.normalizer = normalizer if normalizer is not None else ObservationNormalizer()
        self.health = health if health is not None else ToolHealthTracker(registry, self.settings)
        self.permission_gate = (
            permission_gate if permission_gate is not None else PermissionGate(self.settings)
        )

    async def run(
        self,
        binding: ToolBinding,
        invocation: ToolInvocation,
        ctx: ToolContext | ExecutionContext,
        *,
        index: int = 0,
    ) -> ToolExecution:
        if binding.tool_id != invocation.tool_id:
            raise ValueError(
                "binding.tool_id 与 invocation.tool_id 不一致："
                f"{binding.tool_id} != {invocation.tool_id}"
            )
        defn = binding.definition
        started_at = _now(ctx)
        params = dict(invocation.params)

        if self._is_unavailable(defn.id, started_at):
            return self._terminal(index, defn, params, started_at, "unavailable")

        decision = self._evaluate_permission(defn, invocation, ctx)
        if decision.decision == PERMISSION_DENY:
            return self._terminal(index, defn, params, started_at, "denied", decision=decision)
        if decision.decision == PERMISSION_CONFIRM_REQUIRED:
            return self._terminal(
                index, defn, params, started_at, "pending_confirmation", decision=decision
            )

        validation = None
        if getattr(self.settings, "v24_tool_schema_validation_enabled", False):
            report = self.validator.validate(defn, params, _tool_ctx(ctx))
            if not report.passed:
                return self._terminal(
                    index,
                    defn,
                    params,
                    started_at,
                    "invalid",
                    decision=decision,
                    validation=report.model_dump(mode="json"),
                )
            params = dict(report.normalized)

        return await self._invoke(
            index, defn, params, ctx, started_at, decision, validation
        )

    def _is_unavailable(self, tool_id: str, now: datetime) -> bool:
        """① resolve：先让健康度做冷却半开评估，再读生命周期三层叠加。"""
        self.health.is_tripped(tool_id, now)
        if self.registry.get(tool_id) is None:
            return True
        return self.registry.effective_status(tool_id) != "enabled"

    def _evaluate_permission(
        self,
        defn: ToolDefinition,
        invocation: ToolInvocation,
        ctx: ToolContext | ExecutionContext,
    ) -> PermissionDecision:
        decision = self.permission_gate.evaluate(
            defn,
            invocation,
            PermissionSnapshot(
                user_id=getattr(ctx, "user_id", ""),
                character_id=getattr(ctx, "character_id", "asuna"),
            ),
        )
        if decision.decision in PERMISSION_DECISIONS:
            return decision
        logger.warning(
            "未知权限裁决，按默认拒绝处理：tool_id=%s decision=%s", defn.id, decision.decision
        )
        return PermissionDecision(
            decision=PERMISSION_DENY,
            level=defn.permission.level,
            reason=f"unknown_decision:{decision.decision}",
            scope_required=decision.scope_required,
        )

    async def _invoke(
        self,
        index: int,
        defn: ToolDefinition,
        params: dict[str, Any],
        ctx: ToolContext | ExecutionContext,
        started_at: datetime,
        decision: PermissionDecision,
        validation: dict[str, Any] | None,
    ) -> ToolExecution:
        raw = await self.capability_executor.run(
            ActionStep(
                index=index,
                capability=defn.capability,
                action=defn.action,
                params=params,
            ),
            ctx,
        )
        sensitive = redacted_param_names(defn, params)
        tool_result = self.normalizer.normalize(
            defn,
            raw,
            ExecutionMeta(
                tool_id=defn.id,
                duration_ms=raw.usage.get("duration_ms", 0.0),
                sensitive_param_names=sensitive,
            ),
        )
        self.health.record_outcome(
            defn.id,
            ok=tool_result.status == "succeeded",
            failure_kind=tool_result.failure_kind,
        )
        return ToolExecution(
            index=index,
            tool_id=defn.id,
            capability=defn.capability,
            action=defn.action,
            status=tool_result.status,
            params=redact_params(params, sensitive),
            permission=self._permission_payload(decision),
            validation=validation,
            result=self._persisted(raw, tool_result),
            started_at=started_at,
            duration_ms=_duration_ms(raw),
        )

    def _persisted(self, raw: CapabilityResult, tool_result: ToolResult) -> dict[str, Any]:
        """观测闸 off → V9 原始 `CapabilityResult` 形态；on → ToolResult + 旧 payload 读键。"""
        if not getattr(self.settings, "v24_tool_observation_enabled", False):
            return raw.model_dump(mode="json")
        return persisted_result(tool_result, raw)

    def _terminal(
        self,
        index: int,
        defn: ToolDefinition,
        params: dict[str, Any],
        started_at: datetime,
        status: str,
        *,
        decision: PermissionDecision | None = None,
        validation: dict[str, Any] | None = None,
    ) -> ToolExecution:
        """短路终态：零外部调用、零台账写入，只回填执行形态。"""
        result = ToolResult(
            status=status,
            failure_kind=status if status != "pending_confirmation" else None,
            error=_TERMINAL_ERRORS.get(status, status),
        )
        return ToolExecution(
            index=index,
            tool_id=defn.id,
            capability=defn.capability,
            action=defn.action,
            status=status,
            params=redact_params(params, redacted_param_names(defn, params)),
            permission=self._permission_payload(
                decision
                if decision is not None
                else PermissionDecision(
                    decision=PERMISSION_ALLOW,
                    level=defn.permission.level,
                    reason=PERMISSION_LAYER_OFF_REASON,
                    scope_required=tuple(defn.permission.scope),
                )
            ),
            validation=validation,
            result=result.model_dump(mode="json"),
            started_at=started_at,
            duration_ms=0,
        )

    def _permission_payload(self, decision: PermissionDecision) -> dict[str, Any]:
        return {
            "level": decision.level,
            "decision": decision.decision,
            "reason": decision.reason,
            "confirmed": False,
        }


def _now(ctx: ToolContext | ExecutionContext) -> datetime:
    return getattr(ctx, "now", None) or datetime.now()


def _tool_ctx(ctx: ToolContext | ExecutionContext) -> ToolContext:
    if isinstance(ctx, ToolContext):
        return ctx
    return ToolContext.from_execution_context(ctx)


def _duration_ms(raw: CapabilityResult) -> int:
    value = raw.usage.get("duration_ms", 0.0) if isinstance(raw.usage, dict) else 0.0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
