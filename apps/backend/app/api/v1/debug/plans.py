"""规划域调试端点：计划清单 / 上下文装配投影 / 修订链 / 待推进 / 步骤 / 详情。"""

import logging
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.auth import require_user
from app.api.v1.debug.tools import _tool_registry
from app.api.v1.deps import debug_surface_gate
from app.api.v1.schemas import (
    PlanContextOut,
    PlanDetailOut,
    PlanPendingOut,
    PlanPendingRowOut,
    PlanRevisionRowOut,
    PlanRevisionsOut,
    PlansOut,
    PlanStepRowOut,
    PlanStepsOut,
    PlanSummaryOut,
)
from app.character.asuna.tool import RUN_KIND_AUTONOMOUS_TICK
from app.core.settings import get_settings
from app.models.goal import PLAN_STATUS_VALUES
from app.models.observability import DecisionKind
from app.repositories import decision_repository, goal_repository
from app.services.planning import context as plan_context
from app.services.planning import observer as plan_observer
from app.services.planning import scheduler as plan_scheduler
from app.services.tool.context import ToolContext
from app.services.tool.surface import ToolSurfaceResolver
from app.services.tool.world_context import build_tool_context

logger = logging.getLogger(__name__)


plans_router = APIRouter(
    dependencies=[Depends(debug_surface_gate), Depends(require_user)], tags=["debug"]
)


PLAN_PROJECTION_LIMIT = 200
PLAN_AUDIT_SEARCH_LIMIT = 200

PLAN_SOURCE_NAMES: tuple[str, ...] = (
    "goal",
    "context",
    "world",
    "memory",
    "reflection",
    "tool_surface",
)
"""`/debug/plans/context` 的六源键（architecture §3.3：Goal / Context / World / Memory /
Reflection / ToolSurface）；键集与顺序是本端点的形状契约。"""

PLAN_CONTEXT_PROJECTION_FAILED = "context_projection_failed"
"""装配投影异常的降级标记（§6.5：投影读取异常 → 降级结构 + log，不抛错）。

§6.5 的「降级结构（含 `degraded` 标记）」落在**本面唯一带降级位的输出模型**
（`PlanContextOut`）上：只有上下文装配有「可降级源」这一语义。其余五个端点是纯只读投影
（无降级位），读取失败与既有 `/debug/tools*` 面板同款上抛（`500`）——**不把故障吞成空列表**，
否则调试面会掩盖自己的故障。
"""
def _plan_statuses(status: str | None) -> tuple[str, ...]:
    """状态过滤（§6.1 D3）：缺省 = 全部五态；显式取值越界 → 400（不做静默收敛）。"""
    if status is None:
        return PLAN_STATUS_VALUES
    if status not in PLAN_STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"计划状态取值非法：{status!r}；合法值集: {', '.join(PLAN_STATUS_VALUES)}",
        )
    return (status,)


@dataclass(frozen=True)
class _PlanScheduleContext:
    """`PlanScheduler` 的鸭子类型上下文（§8.4 的 `ctx` 在本端点的只读形态）。

    只投影判定所需的三项：`now`（冷却窗口）、`tool_surface`（面感知）、`settings`
    （既有 `plan_step_cooldown_minutes`）。六源装配**不在此发生**——调度只读计划本体，
    零新增读取面。
    """

    now: datetime
    tool_surface: object | None
    settings: object


def _autonomous_tool_surface(user_id: str, settings, now: datetime):
    """计划的执行面（`RUN_KIND_AUTONOMOUS_TICK`）只读投影：与 `PlanContextAssembler` 同一 Run Profile。

    工具系统总闸 off / 注册表不可得 / 解析失败 → `None`：此时调度**不判** `off_surface`
    （`PlanScheduler` 的缺省语义「缺面即不判」，绝不猜测）。
    """
    base = ToolContext(
        user_id=user_id,
        now=now,
        settings=settings,
        run_kind=RUN_KIND_AUTONOMOUS_TICK,
        source=plan_context.PLAN_TOOL_RUN_SOURCE,
    )
    try:
        if not settings.plan_tool_required:
            return ToolSurfaceResolver(None, settings).resolve(
                RUN_KIND_AUTONOMOUS_TICK, base
            )
        registry = _tool_registry()
        tool_ctx = build_tool_context(base, settings=settings, now=now)
        return ToolSurfaceResolver(registry, settings).resolve(
            RUN_KIND_AUTONOMOUS_TICK, tool_ctx
        )
    except Exception:
        logger.exception("计划调试面工具面投影失败，按无面处理（不判 off_surface）")
        return None


def _schedule_context(user_id: str, settings, now: datetime) -> _PlanScheduleContext:
    return _PlanScheduleContext(
        now=now,
        tool_surface=_autonomous_tool_surface(user_id, settings, now),
        settings=settings,
    )


def _plan_summary(plan) -> PlanSummaryOut:
    return PlanSummaryOut(
        plan_id=plan.id,
        goal_id=plan.goal_id,
        version=plan.version,
        status=plan.status,
        step_count=len(plan.sub_goals),
        updated_at=plan.updated_at,
    )


def _plan_blocking(plan, ctx) -> tuple[int | None, str | None]:
    """计划级阻塞裁决 → (承载它的步序号, 原因)；`(None, None)` = 有可执行步或不可判。

    语义校核：`blocked_reason` 回答的是「**为何此刻没有可执行步**」，属**计划级**裁决，故原因
    只落在当前待推进步（`PlanScheduler.current_step`，执行序中首个未终态步）上，不对其余步
    作推断——同一计划内多个就绪步可能各有不同阻塞因，逐一贴同一原因会是猜测。
    """
    reason = plan_scheduler.PlanScheduler.blocked_reason(plan, ctx)
    if reason is None:
        return None, None
    step = plan_scheduler.PlanScheduler.current_step(plan)
    return (None, None) if step is None else (step.index, reason)


def _plan_step_rows(plan, ctx) -> list[PlanStepRowOut]:
    blocked_index, blocked_reason = _plan_blocking(plan, ctx)
    return [
        PlanStepRowOut(
            index=spec.index,
            description=spec.description,
            kind=spec.kind,
            tool_id=spec.tool_id,
            binding_reason=spec.binding_reason,
            status=spec.status,
            attempt_count=spec.attempt_count,
            blocked_reason=(blocked_reason if spec.index == blocked_index else None),
        )
        for spec in plan.sub_goals
    ]


def _plan_bindings(plan) -> list[dict]:
    return [
        {
            "step_index": spec.index,
            "kind": spec.kind,
            "tool_id": spec.tool_id,
            "binding_reason": spec.binding_reason,
            "capability": spec.capability,
        }
        for spec in plan.sub_goals
    ]


def _plan_criteria(plan) -> list[dict]:
    return [
        {
            "step_index": spec.index,
            "status": spec.status,
            "criteria": spec.criteria,
            "observation_keys": list(spec.observation_keys),
            "expected_effects": list(spec.expected_effects),
        }
        for spec in plan.sub_goals
    ]


def _plan_advance_history(plan) -> list[dict]:
    """推进历史：`decision_records`（`kind='goal_lifecycle'`）里该计划的 `PlanAdvance` 行。

    只读 + 投影：形态不符的行由 `project_plan_advance` 判为 `None` 而跳过（既有 lifecycle
    归因行同样落 `goal_lifecycle` kind，靠 `input_snapshot` 能否还原为 `PlanAdvance` 区分）。
    """
    goal = goal_repository.get_goal(plan.goal_id)
    if goal is None:
        return []
    history: list[dict] = []
    for record in decision_repository.search(
        user_id=goal.user_id,
        kind=DecisionKind.GOAL_LIFECYCLE.value,
        limit=PLAN_AUDIT_SEARCH_LIMIT,
    ):
        advance = plan_observer.project_plan_advance(record)
        if advance is None or advance.plan_id != plan.id:
            continue
        history.append(advance.model_dump(mode="json"))
    return sorted(history, key=lambda item: str(item.get("at") or ""))


def _plan_context_sources(context) -> dict:
    """六源投影（architecture §3.3）。

    脱敏纪律（§5.4）：**记忆与洞察只给计数与 id**（不回显记忆正文与洞察陈述），与既有
    `/debug/memory/{memory_id}/attribution` 的脱敏惯例一致；世界源只给键名与简报长度，
    不回显简报正文。
    """
    brief = context.world_brief
    return {
        "goal": {
            "id": context.goal.id,
            "type": context.goal.type,
            "status": context.goal.status,
            "layer": context.goal.layer,
            "domain": context.goal.domain,
            "priority": context.goal.priority,
            "ancestor_ids": [item.id for item in context.ancestors],
            "sibling_ids": [item.id for item in context.siblings],
        },
        "context": {
            "scene": None if context.scene is None else context.scene.location_id,
            "situation_ids": [situation.id for situation in context.situations],
            "relationship": dict(context.relationship),
            "run": dict(context.run),
        },
        "world": {
            "keys": sorted(context.world.keys()),
            "part_of_day": context.world.get("part_of_day"),
            "location": context.world.get("location"),
            "brief_chars": 0 if brief is None else len(brief.text or ""),
            "world_context_present": context.world_context is not None,
        },
        "memory": {
            "count": len(context.memories),
            "memory_ids": [memory.id for memory in context.memories],
            "types": sorted({memory.type for memory in context.memories if memory.type}),
        },
        "reflection": {
            "count": len(context.insights),
            "insight_ids": [insight.insight_id for insight in context.insights],
            "types": sorted({insight.type for insight in context.insights}),
            "confidences": [insight.confidence for insight in context.insights],
        },
        "tool_surface": {
            "run_kind": context.tool_surface.run_kind,
            "tool_count": len(context.tool_surface.tool_ids),
            "tool_ids": list(context.tool_surface.tool_ids),
            "surface_hash": context.tool_surface.surface_hash,
        },
    }


def _plan_revision_rows(goal_id: str, goal) -> list[PlanRevisionRowOut]:
    """修订链重建（§4.2.4）：链行以 `goal_plans` 版本行**存在**为前提，字段取审计行。

    两张既有表缺一即该步不成立：`goal_plans` 给出该目标的版本行（`from_version` /
    `to_version` 必须真实存在），`decision_records` 给出六字段（`plan_revised` 审计）。
    排序按 `to_version` 升序（链的自然序）。
    """
    versions = {plan.version for plan in goal_repository.list_plans(goal_id)}
    rows: list[PlanRevisionRowOut] = []
    for record in decision_repository.search(
        user_id=goal.user_id,
        kind=DecisionKind.GOAL_LIFECYCLE.value,
        limit=PLAN_AUDIT_SEARCH_LIMIT,
    ):
        revision = plan_observer.project_plan_revision(record)
        if revision is None:
            continue
        snapshot = record.input_snapshot or {}
        if str(snapshot.get("goal_id") or "") != goal_id:
            continue
        if revision.from_version not in versions or revision.to_version not in versions:
            continue
        rows.append(
            PlanRevisionRowOut(
                from_version=revision.from_version,
                to_version=revision.to_version,
                reason=revision.reason,
                trigger_source=revision.trigger_source,
                evidence_refs=list(revision.evidence_refs),
                kept_steps=list(revision.kept_steps),
                at=revision.at,
            )
        )
    return sorted(rows, key=lambda row: row.to_version)


def _load_plan(plan_id: str) -> tuple:
    """计划 + 归属目标（未找到 → 404，与既有 `/debug/tools/{tool_id}` 风格一致）。"""
    plan = goal_repository.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    goal = goal_repository.get_goal(plan.goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="计划归属目标不存在")
    return plan, goal


@plans_router.get("/debug/plans", response_model=PlansOut)
def list_plans(user_id: str, status: str | None = None):
    """计划清单（含版本链与状态）：`goal_id` 相同的多行即该目标的版本链。"""
    plans = goal_repository.list_plans_by_status(user_id, _plan_statuses(status))
    return PlansOut(plans=[_plan_summary(plan) for plan in plans[:PLAN_PROJECTION_LIMIT]])


@plans_router.get("/debug/plans/context", response_model=PlanContextOut)
async def get_plan_context(user_id: str, goal_id: str):
    """`PlanContext` 装配结果投影：六源 + `degraded` 清单（脱敏：记忆 / 洞察只计数与 id）。

    硬依赖不可得（工具系统 off / 注册表不可得 / 目标缺失）时返回**降级结构**
    （`degraded` 记 `PlanUnavailable.reason`），不抛错——与 §6.5 的投影读取异常同款处置。
    """
    goal = goal_repository.get_goal(goal_id)
    if goal is None or (user_id and goal.user_id != user_id):
        raise HTTPException(status_code=404, detail="目标不存在")
    try:
        assembled = await plan_context.PlanContextAssembler().assemble(
            goal, run=None, now=datetime.now()
        )
    except Exception:
        logger.exception("计划上下文装配失败，返回降级结构：%s", goal_id)
        return PlanContextOut(sources={}, degraded=[PLAN_CONTEXT_PROJECTION_FAILED])
    if isinstance(assembled, plan_context.PlanUnavailable):
        return PlanContextOut(sources={}, degraded=[assembled.reason])
    return PlanContextOut(
        sources=_plan_context_sources(assembled),
        degraded=list(assembled.degraded),
    )


@plans_router.get("/debug/plans/revisions", response_model=PlanRevisionsOut)
def list_plan_revisions(goal_id: str):
    """修订链（from/to version + reason + trigger_source + evidence_refs + kept_steps）。"""
    goal = goal_repository.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="目标不存在")
    return PlanRevisionsOut(revisions=_plan_revision_rows(goal_id, goal))


@plans_router.get("/debug/plans/pending", response_model=PlanPendingOut)
def list_pending_plans(user_id: str):
    """待推进步骤（含 `off_surface` / 冷却中 / 前置失败原因）：每个被阻塞的活跃计划一行。"""
    settings = get_settings()
    now = datetime.now()
    ctx = _schedule_context(user_id, settings, now)
    pending: list[PlanPendingRowOut] = []
    for goal, plan in goal_repository.list_active_plans(user_id):
        step_index, reason = _plan_blocking(plan, ctx)
        if step_index is None or reason is None:
            continue
        step = plan_scheduler.PlanScheduler.current_step(plan)
        if step is None:
            continue
        pending.append(
            PlanPendingRowOut(
                goal_id=goal.id,
                plan_id=plan.id,
                step_index=step_index,
                tool_id=step.tool_id,
                reason=reason,
            )
        )
    return PlanPendingOut(pending=pending)


@plans_router.get("/debug/plans/{plan_id}/steps", response_model=PlanStepsOut)
def list_plan_steps(plan_id: str):
    """步骤视图：绑定（`tool_id` / `binding_reason`）与 `blocked_reason` 逐条可读。"""
    plan, goal = _load_plan(plan_id)
    ctx = _schedule_context(goal.user_id, get_settings(), datetime.now())
    return PlanStepsOut(steps=_plan_step_rows(plan, ctx))


@plans_router.get("/debug/plans/{plan_id}", response_model=PlanDetailOut)
def get_plan(plan_id: str):
    """单计划详情：本体 + 步骤 + 绑定 + 判据 + 推进历史（`decision_records` 投影）。"""
    plan, goal = _load_plan(plan_id)
    ctx = _schedule_context(goal.user_id, get_settings(), datetime.now())
    return PlanDetailOut(
        plan=_plan_summary(plan).model_dump(mode="json"),
        steps=_plan_step_rows(plan, ctx),
        bindings=_plan_bindings(plan),
        criteria=_plan_criteria(plan),
        advance_history=_plan_advance_history(plan),
    )
