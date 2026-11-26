"""Planning Integration（RT-009）：Plan 段的规划编排。

把 Planning System（V2.5）接入循环第三段：`Intention` / 目标 → 计划（Goal → Plan → Task）
→ `PlanValue`（运行期**只读投影**）供 Act 消费。规划**只编排不执行**。

边界（RT-009 §3.2 / §4.3）：

- **只编排不执行**（D2）：不调 `PlanScheduler` 推进步骤；推进仍在既有
  `life_loop._execute_active_plans` / 维护步。
- **单一写面**：计划落库只经 `goal_repository`（引擎内部），本段零直接仓储写入。
- **零算法改动**：拆解 / 观察 / 修订 / 校验规则全不动，只调既有引擎。
- **可选段**（D1）：`plan` 环节属 `OPTIONAL_PHASES`；本段再要求 Profile 显式把
  `PLAN_STAGE` 声明进 `optional_stages` 且 `runtime_loop_optional_stages` 启用该环节——
  三 Profile 的 `optional_stages` 默认为空，故**默认永不进入**（前台天然只读，D1）。
- **事务边界**（D3）：异常 / 硬依赖缺失 / 预算跳过路径**零新增计划行**；非 `validated`
  结果一律 `PlanValue=None` 由 Act 回落消费 `Intention`（D5）。
- **降级**：预算跳过与规划失败置 `run.degraded`（RT-006 的 `run_context` 是 Run 的内存载体），
  硬依赖缺失（`PlanUnavailable`）按上游语义视为**正常业务结果**，不置降级。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.core import timeutil
from app.services.goal import service as goal_service
from app.services.planning import scheduler as plan_scheduler

logger = logging.getLogger(__name__)

PLAN_STAGE = "plan"
TRACE_STAGE = "runtime_plan"

REASON_OPTIONAL_DISABLED = "optional_stage_disabled"
REASON_GOAL_MISSING = "goal_missing"
REASON_CONTEXT_UNAVAILABLE = "context_unavailable"
REASON_PLAN_FAILED = "plan_failed"
REASON_PLAN_REJECTED = "plan_rejected"


@dataclass(frozen=True, slots=True)
class PlanStepRef:
    """步骤的只读投影（`SubGoalSpec` → 值对象）。"""

    index: int
    intent: str
    tool_id: str | None
    status: str


@dataclass(frozen=True, slots=True)
class PlanDegradation:
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class PlanValue:
    """运行期只读投影（零新表；`GoalPlanRecord` 模型零改动，D4）。"""

    plan_id: str
    goal_id: str
    status: str
    version: int
    steps: tuple[PlanStepRef, ...]
    current_step: PlanStepRef | None
    budget_skipped: bool
    created_at: datetime
    degradations: tuple[PlanDegradation, ...] = ()

    def degraded(self) -> bool:
        return self.budget_skipped or bool(self.degradations)

    def degraded_reasons(self) -> tuple[str, ...]:
        return tuple(item.reason for item in self.degradations)


def plan_enabled(spec: Any) -> bool:
    """Plan 段启用裁决：可选段开关启用 **且** Profile 显式声明该段为可选。

    复用 RT-006 的 `enabled_optional_phases`（唯一 csv 解析处）；`loop` 为延迟导入
    （`loop` 在本包之上，模块级导入会成环）。
    """
    from app.application.agent_runtime import loop as loop_module

    if loop_module.PHASE_PLAN not in loop_module.enabled_optional_phases():
        return False
    return PLAN_STAGE in spec.optional_stages


def _step_ref(spec: Any) -> PlanStepRef:
    return PlanStepRef(
        index=spec.index,
        intent=spec.description,
        tool_id=spec.tool_id,
        status=spec.status,
    )


def to_plan_value(plan_record: Any, goal_id: str) -> PlanValue:
    """`GoalPlanRecord` → `PlanValue`（步骤序与当前步均用既有 `PlanScheduler` 语义）。"""
    current = plan_scheduler.PlanScheduler.current_step(plan_record)
    return PlanValue(
        plan_id=plan_record.id,
        goal_id=goal_id,
        status=plan_record.status,
        version=plan_record.version,
        steps=tuple(
            _step_ref(spec) for spec in plan_scheduler.PlanScheduler.order(plan_record)
        ),
        current_step=None if current is None else _step_ref(current),
        budget_skipped=False,
        created_at=plan_record.created_at,
    )


def current_plan_value(user_id: str, goal_id: str | None = None) -> PlanValue | None:
    """最近 active 计划的只读投影（多计划取最新；无 active 计划 → `None`）。"""
    if not user_id:
        return None
    for goal, plan in reversed(goal_service.list_active_plans(user_id)):
        if goal_id is None or goal.id == goal_id:
            return to_plan_value(plan, goal.id)
    return None


def _record_trace(
    trace: Any,
    *,
    status: str,
    reason: str,
    goal_id: str | None,
    detail: dict | None = None,
) -> None:
    if trace is None:
        return
    trace.record(
        TRACE_STAGE,
        0.0,
        status=status,
        reason=reason,
        goal_id=goal_id,
        **(detail or {}),
    )


def _mark_degraded(run: Any) -> None:
    if run is not None:
        run.degraded = True


async def plan(
    intention: Any,
    *,
    spec: Any,
    session_context: Any = None,
    run: Any = None,
    llm: Any = None,
    now: datetime | None = None,
    trace: Any = None,
) -> PlanValue | None:
    """`Intention` → `PlanValue`（唯一编排入口）；未启用 / 无目标 / 未通过一律返回 `None`。

    `llm` 仅为签名对齐保留：规划 LLM 面经既有 `goal_planning.propose_plan`（同 prompt、
    同重试语义），本段不引入任何 LLM 直调（§3.2）。
    """
    planned_at = (
        now
        or getattr(run, "started_at", None)
        or getattr(session_context, "started_at", None)
        or timeutil.now()
    )
    goal_id = getattr(intention, "goal_id", None)
    if not plan_enabled(spec):
        _record_trace(
            trace,
            status="skipped",
            reason=REASON_OPTIONAL_DISABLED,
            goal_id=goal_id,
        )
        return None
    if not goal_id:
        _record_trace(
            trace, status="skipped", reason=REASON_GOAL_MISSING, goal_id=None
        )
        return None
    goal = goal_service.get_goal(goal_id)
    if goal is None:
        _record_trace(
            trace, status="skipped", reason=REASON_GOAL_MISSING, goal_id=goal_id
        )
        return None

    from app.services.goal import planning as goal_planning
    from app.services.planning import context as plan_context
    from app.services.planning import engine as plan_engine

    assembled = await plan_context.PlanContextAssembler().assemble(
        goal, run=run, now=planned_at
    )
    if isinstance(assembled, plan_context.PlanUnavailable):
        _record_trace(
            trace,
            status="skipped",
            reason=assembled.reason or REASON_CONTEXT_UNAVAILABLE,
            goal_id=goal_id,
        )
        return None

    try:
        outcome = await plan_engine.get_planning_engine().plan(
            goal, assembled, trigger=goal_planning.TRIGGER_CREATED
        )
    except Exception as exc:  # noqa: BLE001 — 规划失败只降级，不中断循环（D3）
        logger.exception("规划段执行失败：%s", goal_id)
        _mark_degraded(run)
        _record_trace(
            trace,
            status="degraded",
            reason=REASON_PLAN_FAILED,
            goal_id=goal_id,
            detail={"error": exc.__class__.__name__},
        )
        return None

    if outcome.validated:
        value = to_plan_value(outcome.plan, goal_id)
        _record_trace(
            trace,
            status="ok",
            reason="validated",
            goal_id=goal_id,
            detail={"plan_id": value.plan_id, "version": value.version},
        )
        return value

    reason = outcome.rejection_reason or REASON_PLAN_REJECTED
    _mark_degraded(run)
    if outcome.status == plan_engine.PLAN_STATUS_SKIPPED:
        existing = current_plan_value(goal.user_id, goal_id)
        _record_trace(
            trace,
            status="degraded",
            reason=reason,
            goal_id=goal_id,
            detail={"fallback_plan_id": None if existing is None else existing.plan_id},
        )
        if existing is None:
            return None
        return replace(existing, budget_skipped=True)
    _record_trace(trace, status="degraded", reason=reason, goal_id=goal_id)
    return None
