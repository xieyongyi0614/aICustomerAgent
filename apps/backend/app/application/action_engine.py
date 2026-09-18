"""V9 ActionEngine（execution-engine.md §1）。

行动域唯一编排器：create_record → evaluate_gates → assemble_plan →
execute_plan → integrate_result。全部发生在 post_process 第 9 步（per-user 写锁内）
或重试维护循环中。只做调度与容错，检出/闸门/执行逻辑在 services。

V2.4.0：`tool_system_enabled` 开启时 `execute_plan` 的步骤执行改走 `ToolExecutor`
（五段短路 + 结果归一），`steps[]` 增量落 `tool_id` / `permission` / `validation` /
`duration_ms`；总闸关闭时执行路径与 V2.3.0 逐字节一致。

V2.4.0 TOOL-005：权限闸开启时装配 `PermissionSnapshot` 下传执行器（快照装配在引擎侧，
闸门内零 IO）；`pending_confirmation` 步骤登记确认请求并把确认话术投影进行动结果
（回复素材），确认态映射为 `ActionRecord.status="planned"` + `gate_reason=pending_confirmation`；
用户批准后的确认轮次复用原记录与幂等键重新执行（不产生第二条 `ActionRecord`）；
过期确认请求复用既有 action 维护步清理（不新增维护步）。

V2.4.0 TOOL-007：总闸开启时 `_build_snapshot` 经 `WorldContextBuilder` 八段预读世界事实并
注入 `ToolContext`（挂 `snapshot.tool_context`），供工具面投影与工具执行复用；工具写世界
仍只走"`deferred_world_op` → outbox → `world_engine`"唯一路径（本模块不新增写面）。
总闸关闭时不装配（`snapshot.tool_context is None`），行为与 V2.3.0 逐字节一致。
"""

import asyncio
import logging
from datetime import datetime, timedelta

from app.character.asuna.action import ACTION_CAPABILITY_MAP
from app.core.settings import get_settings
from app.models.action import (
    ActionEffect,
    ActionResult,
    ActionPlan,
    ActionRecord,
    ActionIntent,
    ActionStep,
    transition_action,
)
from app.models.tool import ToolInvocation
from app.repositories import action_repository
from app.services.action.executor import CapabilityExecutor
from app.services.action.planner import GateSnapshot, assemble_plan, evaluate_gates
from app.services.action.registry import ExecutionContext, get_capability_registry
from app.services.tool.confirmation import get_confirmation_service
from app.services.tool.context import DEFAULT_SOURCE, ToolContext
from app.services.tool.executor import ToolExecutor, resolve_step_binding
from app.services.tool.health import ToolHealthTracker
from app.services.tool.permission import (
    CONFIRM_KIND_ALWAYS,
    CONFIRM_KIND_FIRST_TIME,
    CONFIRM_POLICY_ALWAYS,
    PermissionDecision,
    PermissionSnapshot,
    ToolPermissionGate,
    build_confirm_prompt,
    confirm_policy,
    required_scope,
)
from app.services.tool.registry import ToolRegistry, get_tool_registry
from app.services.tool.world_context import WORLD_FACTS_KEYS, apply_world_facts, build_tool_context
from app.application import world_engine
from app.application.worker_loop import run_worker_loop
from app.services.action import memory_bridge, relationship_bridge

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("created", "planned", "executing")
RETRYABLE_FAILURES = ("transient", "timeout")

GATE_REASON_PENDING_CONFIRMATION = "pending_confirmation"
GATE_REASON_PERMISSION_DENIED = "permission_denied"

_TOOL_STEP_STATUSES: dict[str, str] = {
    "succeeded": "succeeded",
    "failed": "failed",
    "timeout": "failed",
    "unavailable": "skipped",
    "denied": "skipped",
    "invalid": "skipped",
    "pending_confirmation": "skipped",
}

_TOOL_RECORD_OUTCOMES: dict[str, tuple[str, str]] = {
    "unavailable": ("cancelled", "capability_unavailable"),
    "denied": ("cancelled", "permission_denied"),
    "invalid": ("cancelled", "invalid_params"),
    "pending_confirmation": ("planned", "pending_confirmation"),
}

_TOOL_ACTION_FAILURE_KINDS: dict[str, str] = {
    "invalid": "permanent",
    "denied": "permanent",
    "unavailable": "unavailable",
    "timeout": "timeout",
    "transient": "transient",
    "permanent": "permanent",
}


def _now() -> datetime:
    return datetime.now()


def new_record(
    intent: ActionIntent,
    user_id: str,
    session_id: str | None,
    source: str = "conversation",
    *,
    run_id: str | None = None,
) -> ActionRecord:
    return ActionRecord(
        id=action_repository.new_record_id(),
        user_id=user_id,
        session_id=session_id,
        run_id=run_id,
        source=source,
        action_type=intent.action_type,
        intent=intent.model_dump(mode="json"),
        dedupe_key=intent.dedupe_key,
        params=intent.params,
        status="created",
        created_at=_now(),
        updated_at=_now(),
    )


def _build_snapshot(user_id: str, settings) -> GateSnapshot:
    """装配六闸门快照（读世界现状与既有记录，闸门内零 IO）。

    V2.4.0 TOOL-007：总闸开启时额外装配 `ToolContext`（八段世界事实预读）并挂到
    `snapshot.tool_context`，供闸门后的工具面投影与工具执行复用（同一快照，零重复 IO）；
    总闸关闭返回 `None` → 投影与执行走 V9 原路径，行为与 V2.3.0 一致。
    """
    snapshot = GateSnapshot(settings=settings, registry=get_capability_registry(), now=_now())
    snapshot.records = [
        {
            "id": r.id,
            "dedupe_key": r.dedupe_key,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in action_repository.list_records(user_id, limit=200)
    ]
    snapshot.active_count = sum(1 for r in snapshot.records if r["status"] in ACTIVE_STATUSES)
    try:
        world = world_engine.get_world(user_id)
        if world is not None:
            snapshot.world_available = getattr(settings, "world_enabled", True)
        snapshot.active_object_names = [o.name for o in world_engine.list_active_objects(user_id)]
        events = world_engine.list_active_events(user_id)
        snapshot.active_reminder_titles = [e.title for e in events if e.type in ("reminder", "appointment")]
    except Exception:
        logger.exception("世界快照装配失败，G6 退化为不否决")
    snapshot.tool_context = _build_tool_context(user_id, settings, snapshot.now, snapshot.run_kind)
    return snapshot


def _build_tool_context(
    user_id: str, settings, now: datetime, run_kind: str
) -> ToolContext | None:
    """工具上下文预读（TOOL-007 §2.3）：总闸 off → `None`（零 IO，V2.3.0 行为）。

    装配失败不抛出（`WorldContextBuilder` 逐段降级）；本函数自身异常同样降级为
    `None`——工具系统是行动链路的旁路，任何失败都不得影响行动规划。
    """
    if not getattr(settings, "tool_system_enabled", False):
        return None
    try:
        base = ToolContext(
            user_id=user_id,
            now=now,
            settings=settings,
            run_kind=run_kind,
            source=DEFAULT_SOURCE,
        )
        return build_tool_context(base, settings=settings, now=now)
    except Exception:
        logger.exception("工具上下文预读失败，降级为空世界事实")
        return None


def _tool_context_for_execution(
    ctx: ExecutionContext, preloaded: ToolContext | None
) -> ToolContext:
    """执行用 `ToolContext`：执行上下文定身份（record_id / now / settings），
    预读快照供世界事实（TOOL-007 §2.3"预读注入"）；未预读则世界事实留空（降级）。"""
    base = ToolContext.from_execution_context(ctx)
    if preloaded is None:
        return base
    return apply_world_facts(base, {key: getattr(preloaded, key) for key in WORLD_FACTS_KEYS})


async def execute_plan(
    record: ActionRecord,
    plan: ActionPlan,
    ctx: ExecutionContext,
    *,
    permission_snapshot: PermissionSnapshot | None = None,
    tool_context: ToolContext | None = None,
) -> ActionResult:
    """执行计划：step 归一回填 steps/result；重试保留同 Record。

    `tool_context`（TOOL-007）：`_build_snapshot` 预读的世界事实快照；缺省时按执行上下文
    重建（世界事实留空）——总闸 off 的路径行为与 V2.3.0 逐字节一致。
    V2.6.0：总闸 on 时经 ActionExecutor 统一分派；off 时保持既有路径。
    """
    settings = get_settings()
    storage = get_capability_registry()
    executor = CapabilityExecutor(storage, settings.action_execution_timeout_seconds)
    record.status = "executing"
    record.executed_at = _now()
    record.updated_at = _now()
    action_repository.save_record(record)

    if _action_execution_enabled(settings):
        return await _execute_plan_via_action_executor(
            record,
            plan,
            ctx,
            settings,
            storage,
            executor,
            permission_snapshot=permission_snapshot,
            tool_context=tool_context,
        )

    tool_registry = get_tool_registry() if settings.tool_system_enabled else None
    if tool_registry is not None:
        return await _execute_plan_via_tools(
            record,
            plan,
            ctx,
            settings,
            executor,
            tool_registry,
            permission_snapshot=permission_snapshot,
            tool_context=tool_context,
        )

    step_dicts: list[dict] = []
    for step in plan.steps:
        result = await executor.run(step, ctx)
        step_dicts.append(
            {
                "index": step.index,
                "capability": step.capability,
                "action": step.action,
                "params": step.params,
                "status": "failed" if result.status != "succeeded" else "succeeded",
                "result": result.model_dump(mode="json"),
            }
        )

    record.steps = step_dicts
    all_ok = all(s["status"] == "succeeded" for s in record.steps)
    if all_ok:
        result_out = ActionResult(status="succeeded", effects=[])
        record.status = transition_action("executing", "step_all_succeeded") or record.status
    else:
        step_result = record.steps[0].get("result", {})
        failure_kind = (step_result.get("payload") or {}).get("failure_kind") or "transient"
        result_out = ActionResult(
            status="failed",
            effects=[],
            error=str(step_result.get("error"))[:80],
            failure_kind=failure_kind,
        )
        if failure_kind in RETRYABLE_FAILURES and record.attempt < settings.action_retry_max_attempts:
            record.status = "executing"
            record.attempt += 1
            backoff = settings.action_retry_backoff_seconds * (2 ** (record.attempt - 1))
            record.next_retry_at = _now() + timedelta(seconds=backoff)
        else:
            record.status = transition_action(
                "executing",
                "step_retryable_failed"
                if failure_kind in RETRYABLE_FAILURES
                else "step_permanent_failed",
                attempts_exceeded=True,
            ) or "failed"
    record.result = result_out.model_dump(mode="json")
    record.updated_at = _now()
    action_repository.save_record(record)
    return result_out


def _action_execution_enabled(settings) -> bool:
    return bool(getattr(settings, "action_execution_enabled", False))


async def _execute_plan_via_action_executor(
    record: ActionRecord,
    plan: ActionPlan,
    ctx: ExecutionContext,
    settings,
    storage,
    capability_executor: CapabilityExecutor,
    *,
    permission_snapshot: PermissionSnapshot | None = None,
    tool_context: ToolContext | None = None,
) -> ActionResult:
    """V2.6.0 主路径：ActionExecutor 统一分派 Internal/Tool/External。"""
    from app.models.action import Action
    from app.services.action.executor import ActionExecutor
    from app.services.tool.executor import ToolExecutor
    from app.services.tool.health import ToolHealthTracker

    tool_executor = None
    tool_resolver = None
    exec_tool_ctx = tool_context
    if settings.tool_system_enabled:
        tool_registry = get_tool_registry()
        tool_executor = ToolExecutor(
            tool_registry,
            capability_executor,
            settings=settings,
            health=ToolHealthTracker(tool_registry, settings),
        )

        def tool_resolver(action: Action):
            step = ActionStep(
                index=0,
                capability="",
                action="",
                params=dict(action.parameters or {}),
            )
            if plan.steps:
                step = plan.steps[0]
            binding = resolve_step_binding(tool_registry, step)
            if binding is None:
                return None, None
            intent = (
                ActionIntent.model_validate(record.intent)
                if record.intent
                else plan.intent
            )
            invocation = ToolInvocation(
                tool_id=binding.tool_id,
                params=dict(step.params if plan.steps else action.parameters or {}),
                rationale=str((record.intent or {}).get("evidence", "")),
                source=record.source,
                intent=intent,
                goal_id=record.goal_id,
                dedupe_key=record.dedupe_key,
            )
            return binding, invocation

        if exec_tool_ctx is None:
            exec_tool_ctx = _tool_context_for_execution(ctx, tool_context)

    action_executor = ActionExecutor(
        storage,
        timeout_seconds=settings.action_execution_timeout_seconds,
        tool_executor=tool_executor,
        tool_resolver=tool_resolver,
        permission_snapshot=permission_snapshot,
        tool_context=exec_tool_ctx,
    )
    action = Action(
        id=record.id,
        type=record.action_type,
        target=record.user_id,
        parameters=dict(record.params or {}),
        priority=record.priority,
        status=record.status,
        created_at=record.created_at,
        source=record.source,
        goal_id=record.goal_id,
        dedupe_key=record.dedupe_key,
        run_id=record.session_id,
    )
    result_out = await action_executor.run(action, ctx)
    from app.services.action.executor import step_extras_from_result, step_result_payload

    capability_name, capability_action = ACTION_CAPABILITY_MAP.get(
        record.action_type, ("", "")
    )
    extras = step_extras_from_result(result_out)
    step_status = (
        "succeeded"
        if result_out.status == "succeeded"
        else ("partial" if result_out.status == "partial" else "failed")
    )
    step_dicts = [
        {
            "index": 0,
            "capability": capability_name,
            "action": capability_action,
            "params": dict(record.params or {}),
            "status": step_status,
            "result": step_result_payload(result_out),
            **extras,
        }
    ]
    record.steps = step_dicts
    _apply_action_result_to_record(record, result_out, settings)
    record.result = step_result_payload(result_out)
    record.updated_at = _now()
    action_repository.save_record(record)
    return result_out


def _apply_action_result_to_record(record: ActionRecord, result_out: ActionResult, settings) -> None:
    if result_out.status == "succeeded":
        record.status = transition_action("executing", "step_all_succeeded") or record.status
        return
    if result_out.status == "partial":
        record.status = "failed"
        record.gate_reason = result_out.failure_kind or "partial"
        return
    failure_kind = result_out.failure_kind or "transient"
    if failure_kind in RETRYABLE_FAILURES and record.attempt < settings.action_retry_max_attempts:
        record.status = "executing"
        record.attempt += 1
        backoff = settings.action_retry_backoff_seconds * (2 ** (record.attempt - 1))
        record.next_retry_at = _now() + timedelta(seconds=backoff)
        return
    event = (
        "step_retryable_failed"
        if failure_kind in RETRYABLE_FAILURES
        else "step_permanent_failed"
    )
    record.status = transition_action("executing", event, attempts_exceeded=True) or "failed"


async def execute_existing_record(
    record: ActionRecord, *, session_id: str | None = None
) -> ActionResult | None:
    """复用既有 ActionRecord 执行（Manager.execute 唯一委托入口，不新建记录）。"""
    settings = get_settings()
    if not settings.action_enabled:
        return None
    if record.status not in ("created", "planned", "executing"):
        return None
    intent_data = record.intent or {}
    if not intent_data:
        record.status = transition_action(
            record.status if record.status != "executing" else "executing",
            "step_permanent_failed",
            attempts_exceeded=True,
        ) or "failed"
        record.updated_at = _now()
        action_repository.save_record(record)
        return ActionResult(
            status="failed", error="missing_intent", failure_kind="permanent"
        )
    intent = ActionIntent.model_validate(intent_data)
    if record.status == "created":
        snapshot = _build_snapshot(record.user_id, settings)
        snapshot.records = [r for r in snapshot.records if r.get("id") != record.id]
        snapshot.active_count = sum(
            1 for r in snapshot.records if r["status"] in ACTIVE_STATUSES
        )
        decision = evaluate_gates(intent, snapshot)
        if not decision.allowed:
            record.status = transition_action("created", "gate_reject") or "cancelled"
            record.gate_reason = decision.reason
            record.updated_at = _now()
            action_repository.save_record(record)
            return ActionResult(
                status="failed",
                error=str(decision.reason or "gate_reject"),
                failure_kind="permanent",
            )
        record.status = transition_action("created", "gate_pass") or "planned"
        record.updated_at = _now()
        action_repository.save_record(record)
    else:
        snapshot = _build_snapshot(record.user_id, settings)

    if record.status == "planned":
        started = transition_action("planned", "execute_start")
        if started is None:
            return None
        record.status = started
        record.updated_at = _now()
        action_repository.save_record(record)

    plan = assemble_plan(intent, snapshot, _now(), goal_id=record.goal_id)
    if plan is None:
        record.status = "cancelled"
        record.gate_reason = "capability_unavailable"
        record.updated_at = _now()
        action_repository.save_record(record)
        return ActionResult(
            status="failed",
            error="capability_unavailable",
            failure_kind="unavailable",
        )
    if session_id is not None and record.session_id is None:
        record.session_id = session_id
    ctx = ExecutionContext(
        user_id=record.user_id,
        character_id=record.character_id,
        record_id=record.id,
        now=_now(),
        settings=settings,
    )
    result = await execute_plan(
        record,
        plan,
        ctx,
        permission_snapshot=_build_permission_snapshot(record.user_id, settings),
        tool_context=snapshot.tool_context,
    )
    if record.status != "failed":
        _apply_feedback(record, result)
    else:
        record.updated_at = _now()
        action_repository.save_record(record)
    return result


async def _execute_plan_via_tools(
    record: ActionRecord,
    plan: ActionPlan,
    ctx: ExecutionContext,
    settings,
    capability_executor: CapabilityExecutor,
    tool_registry: ToolRegistry,
    *,
    permission_snapshot: PermissionSnapshot | None = None,
    tool_context: ToolContext | None = None,
) -> ActionResult:
    """总闸开启时的执行路径：五段短路 + `steps[]` 新字段（TOOL-003 §2.2、§2.4）。"""
    tool_executor = ToolExecutor(
        tool_registry,
        capability_executor,
        settings=settings,
        health=ToolHealthTracker(tool_registry, settings),
    )
    tool_ctx = _tool_context_for_execution(ctx, tool_context)
    intent = ActionIntent.model_validate(record.intent) if record.intent else plan.intent

    step_dicts: list[dict] = []
    statuses: list[str] = []
    confirm_prompt: str | None = None
    for step in plan.steps:
        binding = resolve_step_binding(tool_registry, step)
        if binding is None:
            logger.warning(
                "工具层无法解析步骤绑定，判为不可用: capability=%s action=%s",
                step.capability,
                step.action,
            )
            step_dicts.append(_unresolved_step_dict(step))
            statuses.append("unavailable")
            break
        invocation = ToolInvocation(
            tool_id=binding.tool_id,
            params=dict(step.params),
            rationale=str(record.intent.get("evidence", "")),
            source=record.source,
            intent=intent,
            goal_id=record.goal_id,
            dedupe_key=record.dedupe_key,
        )
        execution = await tool_executor.run(
            binding,
            invocation,
            tool_ctx,
            index=step.index,
            permission_snapshot=permission_snapshot,
        )
        step_dicts.append(_tool_step_dict(step, execution))
        statuses.append(execution.status)
        if execution.status == "pending_confirmation":
            confirm_prompt = _register_confirmation(
                binding.definition, invocation, execution, tool_ctx, settings
            )
        if execution.status not in ("succeeded", "failed", "timeout"):
            break

    record.steps = step_dicts
    outcome = next((status for status in statuses if status != "succeeded"), "succeeded")
    if outcome in _TOOL_RECORD_OUTCOMES:
        record.status, record.gate_reason = _TOOL_RECORD_OUTCOMES[outcome]
        result_out = _tool_action_result(record, outcome, step_dicts, confirm_prompt)
    else:
        result_out = _settle_executed_record(record, settings, step_dicts)
    record.result = result_out.model_dump(mode="json")
    record.updated_at = _now()
    action_repository.save_record(record)
    return result_out


def _register_confirmation(
    definition,
    invocation: ToolInvocation,
    execution,
    tool_ctx: ToolContext,
    settings,
) -> str | None:
    """确认请求登记（TOOL-005 §2.3）：闸门内零 IO，DB 写只发生在执行器之外的本函数。"""
    payload = dict(execution.permission or {})
    decision = PermissionDecision(
        decision=str(payload.get("decision") or "confirm_required"),
        level=payload.get("level") or definition.permission.level,
        reason=str(payload.get("reason") or "confirm_required"),
        confirm_prompt=build_confirm_prompt(definition, invocation),
        scope_required=required_scope(definition),
        confirm_kind=_confirm_kind(definition),
    )
    request = get_confirmation_service(settings).request(invocation, decision, tool_ctx)
    if request is None:
        logger.warning("确认请求登记失败，本轮不执行外部调用：tool_id=%s", definition.id)
        return None
    return request.prompt


def _confirm_kind(definition) -> str:
    if confirm_policy(definition) == CONFIRM_POLICY_ALWAYS:
        return CONFIRM_KIND_ALWAYS
    return CONFIRM_KIND_FIRST_TIME


def _build_permission_snapshot(
    user_id: str, settings
) -> PermissionSnapshot | None:
    """权限快照装配（TOOL-005 §2.2）：唯一读 IO 入口在 `ToolPermissionGate.build_snapshot`。

    装配在引擎侧完成并下传执行器，使权限闸内（`evaluate`）保持零 IO；双闸未全开返回
    `None`（不产生读 IO），执行器据此走 TOOL-003 交付态。
    """
    if not (
        getattr(settings, "tool_system_enabled", False)
        and getattr(settings, "tool_permission_enabled", False)
    ):
        return None
    return ToolPermissionGate(settings).build_snapshot(user_id, _now(), settings)


def _settle_executed_record(
    record: ActionRecord, settings, step_dicts: list[dict]
) -> ActionResult:
    """已触达能力的步骤按 V9 既有语义结账（成功终态 / 失败退避）。"""
    all_ok = all(s["status"] == "succeeded" for s in step_dicts)
    if all_ok:
        record.status = transition_action("executing", "step_all_succeeded") or record.status
        return ActionResult(status="succeeded", effects=[])
    step_result = dict(step_dicts[0].get("result") or {})
    payload = step_result.get("payload") or {}
    failure_kind = (
        step_result.get("failure_kind") or payload.get("failure_kind") or "transient"
    )
    result_out = ActionResult(
        status="failed",
        effects=[],
        error=str(step_result.get("error"))[:80],
        failure_kind=_TOOL_ACTION_FAILURE_KINDS.get(str(failure_kind), "transient"),
    )
    if failure_kind in RETRYABLE_FAILURES and record.attempt < settings.action_retry_max_attempts:
        record.status = "executing"
        record.attempt += 1
        backoff = settings.action_retry_backoff_seconds * (2 ** (record.attempt - 1))
        record.next_retry_at = _now() + timedelta(seconds=backoff)
    else:
        record.status = transition_action(
            "executing",
            "step_retryable_failed"
            if failure_kind in RETRYABLE_FAILURES
            else "step_permanent_failed",
            attempts_exceeded=True,
        ) or "failed"
    return result_out


def _tool_action_result(
    record: ActionRecord,
    outcome: str,
    step_dicts: list[dict],
    confirm_prompt: str | None = None,
) -> ActionResult:
    """闸门段失败（unavailable / denied / invalid）与待确认行动的 ActionResult 投影。

    待确认时不执行外部调用，`error` 承载确认话术（角色语气）供回复素材取材（TOOL-005 §2.3）。
    """
    step_result = dict(step_dicts[0].get("result") or {}) if step_dicts else {}
    detail = step_result.get("error") or _TOOL_RECORD_OUTCOMES[outcome][1]
    if outcome == GATE_REASON_PENDING_CONFIRMATION and confirm_prompt:
        detail = confirm_prompt
    return ActionResult(
        status="failed",
        effects=[],
        error=str(detail)[:80],
        failure_kind=_TOOL_ACTION_FAILURE_KINDS.get(outcome, "permanent"),
    )


def _tool_step_dict(step, execution) -> dict:
    return {
        "index": step.index,
        "capability": step.capability,
        "action": step.action,
        "params": execution.params,
        "status": _TOOL_STEP_STATUSES[execution.status],
        "result": execution.result,
        "tool_id": execution.tool_id,
        "permission": execution.permission,
        "validation": execution.validation,
        "duration_ms": execution.duration_ms,
    }


def _unresolved_step_dict(step) -> dict:
    return {
        "index": step.index,
        "capability": step.capability,
        "action": step.action,
        "params": step.params,
        "status": "skipped",
        "result": {
            "status": "unavailable",
            "failure_kind": "unavailable",
            "error": "工具不可用（未注册 / 已禁用 / 已熔断）",
        },
        "tool_id": None,
        "permission": {},
        "validation": None,
        "duration_ms": 0,
    }


def _append_effect(record: ActionRecord, kind: str, ref: str, detail: str) -> None:
    result = ActionResult(**record.result) if record.result else ActionResult(status="succeeded", effects=[])
    result.effects.append(ActionEffect(kind=kind, ref=ref, detail=detail[:200]))
    record.result = result.model_dump(mode="json")


def _effect_ref(step_result: dict, kind: str) -> str | None:
    """新键优先：从 `ToolResult.effects`（V2.4.0）取效果引用；缺省返回 None 走旧键兜底。"""
    effects = step_result.get("effects")
    if not isinstance(effects, list):
        return None
    for effect in effects:
        if isinstance(effect, dict) and effect.get("kind") == kind and effect.get("ref"):
            return str(effect["ref"])
    return None


def _deliver_memory(record: ActionRecord, settings) -> dict | None:
    """记忆投递路由（TOOL-008 §2.3）：工具记忆子闸 on 走泛化键，off 与 V9 逐字节一致。"""
    if getattr(settings, "tool_memory_enabled", False):
        return memory_bridge.deliver(record, record.user_id, record.character_id)
    return memory_bridge.deliver_action_memory(record, record.user_id, record.character_id)


def integrate_result(record: ActionRecord, result: ActionResult) -> None:
    """结果整合四通道（execution-engine.md §1）：世界/记忆/关系/note。

    V2.4.0：效果引用读 `steps[].result.effects`（新键）优先，`payload` 旧键兜底——
    兼容窗口 ≥ 一个版本，Flag off 时等价于 V9 原路径。
    V2.4.0 TOOL-008：记忆投递经 `_deliver_memory` 路由，子闸 off 时调用与参数不变。
    V2.6.1：反馈投影不在本函数内联——唯一入口为 `integration.apply_result_feedback`。
    """
    settings = get_settings()

    effects = list(result.effects)
    if record.status == "succeeded":
        payloads = [(s.get("result") or {}).get("payload", {}) for s in record.steps]
        first_payload = next(iter(payloads)) if payloads else {}
        first_result = (record.steps[0].get("result") or {}) if record.steps else {}
        if record.action_type in ("create_reminder", "cancel_reminder"):
            event_id = _effect_ref(first_result, "world") or first_payload.get("world_event_id")
            if event_id:
                effects.append(ActionEffect(kind="world", ref=event_id, detail=_detail_for(record)))
        if record.action_type == "remember_fact":
            memory_id = _effect_ref(first_result, "memory") or first_payload.get("memory_id")
            if memory_id:
                effects.append(ActionEffect(kind="memory", ref=memory_id, detail="已记住"))

    minimal = ActionResult(
        status=result.status,
        effects=effects,
        error=result.error,
        failure_kind=result.failure_kind,
    ).model_dump(mode="json")
    existing = record.result if isinstance(record.result, dict) else None
    if existing and "payload" in existing:
        merged = dict(existing)
        merged.update(
            {
                "status": minimal["status"],
                "effects": minimal["effects"],
                "error": minimal["error"],
                "failure_kind": minimal["failure_kind"],
            }
        )
        record.result = merged
    else:
        record.result = minimal

    if settings.action_outbox_enabled:
        _integrate_via_outbox(record)
        return

    if settings.action_enabled:
        memory_payload = _deliver_memory(record, settings)
        if memory_payload:
            _append_effect(record, "memory", memory_payload.get("memory_id", ""), "已记住")
        relationship_bridge.deliver_action_signal(record, record.user_id)

    record.updated_at = _now()
    action_repository.save_record(record)


def _apply_feedback(record: ActionRecord, result: ActionResult) -> None:
    """主路径唯一反馈入口：委托 `integration.apply_result_feedback`。"""
    from app.services.action import integration as action_integration

    action_integration.apply_result_feedback(record, result)


def _integrate_via_outbox(record: ActionRecord) -> None:
    """Outbox 模式（LIFE-004）：跨域投递延迟化——行动终态与 outbox 登记同事务
    落库（幂等键 = action_id），世界/关系效果由消费器经既有引擎函数落库；
    记忆沉淀由 P1 摄取补扫按幂等键收敛（本路径不再调 memory_bridge 直写）。
    """

    world_ops = []
    for step in record.steps:
        payload = (step.get("result") or {}).get("payload", {}) or {}
        op = payload.get("deferred_world_op")
        if op:
            world_ops.append(op)
    payload = {
        "action_id": record.id,
        "user_id": record.user_id,
        "record": record.model_dump(mode="json"),
        "world_ops": world_ops,
    }
    record.updated_at = _now()
    action_repository.save_record_with_outbox(record, payload, idempotency_key=record.id)


def _detail_for(record: ActionRecord) -> str:
    content = str(record.params.get("content", ""))
    due = record.params.get("due_at")
    return f"创建提醒 WorldEvent due {due}" if due else f"创建提醒 {content}"


async def run_action_planning(
    user_id: str, intent: ActionIntent, session_id: str | None = None,
    goal_id: str | None = None, source: str = "conversation",
) -> ActionRecord | None:
    """第 9 步入口：门控 + 建记录 + 六闸门 + 装配 + 执行 + 整合。"""
    settings = get_settings()
    if not settings.action_enabled or intent is None:
        return None
    record = new_record(intent, user_id, session_id, source)

    snapshot = _build_snapshot(user_id, settings)
    decision = evaluate_gates(intent, snapshot)
    if not decision.allowed:
        record.status = "cancelled"
        record.gate_reason = decision.reason
        record.updated_at = _now()
        action_repository.save_record(record)
        return record

    record.status = "planned"
    record.updated_at = _now()
    action_repository.save_record(record)

    plan = assemble_plan(intent, snapshot, _now(), goal_id=goal_id)
    if plan is None:
        record.status = "cancelled"
        record.gate_reason = "capability_unavailable"
        record.updated_at = _now()
        action_repository.save_record(record)
        return record

    ctx = ExecutionContext(
        user_id=user_id, character_id=record.character_id, record_id=record.id,
        now=_now(), settings=settings,
    )
    result = await execute_plan(
        record, plan, ctx, permission_snapshot=_build_permission_snapshot(user_id, settings),
        tool_context=snapshot.tool_context,
    )
    if record.status != "failed":
        _apply_feedback(record, result)
    else:
        record.updated_at = _now()
        action_repository.save_record(record)
    return record


async def run_confirmation_round(
    user_id: str,
    request_id: str,
    *,
    approved: bool,
    session_id: str | None = None,
) -> ActionRecord | None:
    """确认轮次（TOOL-005 §2.3 步骤④）：以原 `invocation_snapshot` 与 `dedupe_key` 复用原记录。

    批准 → 原记录（六闸门首次已过，状态 `planned`）直接从 `executing` 续跑，**不产生第二条
    `ActionRecord`**、不重新抽取参数、不重新评估 G4（避免自我去重）；否定 / 过期 → 原记录转
    `cancelled` + `permission_denied`，工具不执行（零外部调用）。
    """
    settings = get_settings()
    if not settings.action_enabled:
        return None
    service = get_confirmation_service(settings)
    outcome = service.resolve(request_id, approved=approved, source="user_confirm")
    request = outcome.request
    if request is None:
        logger.info("确认请求不存在，确认轮次跳过：request_id=%s", request_id)
        return None
    record = _pending_confirmation_record(user_id, request.dedupe_key)
    if outcome.status != "approved":
        if record is None:
            return None
        record.status = "cancelled"
        record.gate_reason = GATE_REASON_PERMISSION_DENIED
        record.updated_at = _now()
        action_repository.save_record(record)
        return record
    if record is None:
        logger.warning(
            "确认请求已批准但未找到待确认行动记录，不新建记录：request_id=%s", request_id
        )
        return None
    try:
        return await _resume_confirmed_record(record, request, settings, session_id)
    finally:
        if not service.confirm_ttl_reuse():
            service.release_session_grant(user_id, request.tool_id)


async def _resume_confirmed_record(
    record: ActionRecord, request, settings, session_id: str | None
) -> ActionRecord:
    intent = _confirmed_intent(record, request)
    snapshot = _build_snapshot(record.user_id, settings)
    plan = assemble_plan(intent, snapshot, _now(), goal_id=record.goal_id)
    if plan is None:
        record.status = "failed"
        record.gate_reason = "capability_unavailable"
        record.updated_at = _now()
        action_repository.save_record(record)
        return record
    record.intent = intent.model_dump(mode="json")
    record.params = dict(intent.params)
    record.dedupe_key = intent.dedupe_key
    record.gate_reason = None
    if session_id is not None:
        record.session_id = session_id
    ctx = ExecutionContext(
        user_id=record.user_id,
        character_id=record.character_id,
        record_id=record.id,
        now=_now(),
        settings=settings,
    )
    result = await execute_plan(
        record,
        plan,
        ctx,
        permission_snapshot=_build_permission_snapshot(record.user_id, settings),
        tool_context=snapshot.tool_context,
    )
    if record.status != "failed":
        _apply_feedback(record, result)
    else:
        record.updated_at = _now()
        action_repository.save_record(record)
    return record


def _confirmed_intent(record: ActionRecord, request) -> ActionIntent:
    """原调用快照优先（参数与幂等键原样复用），缺省回退记录意图。"""
    try:
        intent = request.invocation().intent
    except Exception:
        logger.exception("确认请求快照还原失败，回退记录意图：request_id=%s", request.request_id)
        intent = ActionIntent.model_validate(record.intent)
    dedupe_key = request.dedupe_key or intent.dedupe_key or record.dedupe_key
    return intent.model_copy(update={"dedupe_key": dedupe_key, "confidence": "confident"})


def _pending_confirmation_record(user_id: str, dedupe_key: str) -> ActionRecord | None:
    if not dedupe_key:
        return None
    window = timedelta(hours=get_settings().action_dedupe_window_hours)
    try:
        records = action_repository.list_by_dedupe(user_id, dedupe_key, _now() - window)
    except Exception:
        logger.exception("待确认行动记录查询失败：dedupe_key=%s", dedupe_key)
        return None
    for record in records:
        if record.gate_reason == GATE_REASON_PENDING_CONFIRMATION and record.status == "planned":
            return record
    return None


def collect_facts(user_id: str) -> dict:
    """有界 action_facts 事实包（autonomy-integration.md §2，H-A5）。失败返回 {}。"""
    try:
        if not get_settings().action_enabled:
            return {}
        records = action_repository.list_records(user_id, limit=50)
        active = [r for r in records if r.status in ACTIVE_STATUSES]
        reminders = [
            r
            for r in records
            if r.action_type == "create_reminder" and r.status == "succeeded"
        ]
        pending_reminders = []
        now = _now()
        for r in reminders:
            due = r.params.get("due_at")
            if not due:
                continue
            try:
                due_at = datetime.fromisoformat(str(due))
                due_in_hours = (due_at - now).total_seconds() / 3600
            except ValueError:
                continue
            pending_reminders.append(
                {"title": str(r.params.get("content", ""))[:20], "due_in_hours": round(due_in_hours, 1)}
            )
        recent_failures = [
            {"action": r.action_type, "reason": (r.gate_reason or "执行失败")}
            for r in records
            if r.status == "failed"
        ][:3]
        recent_feedback = []
        for r in records:
            stored = r.result if isinstance(r.result, dict) else None
            if not stored or stored.get("feedback_kinds") is None:
                continue
            recent_feedback.append(
                {
                    "action": r.action_type,
                    "status": r.status,
                    "feedback_kinds": list(stored.get("feedback_kinds") or []),
                    "temporary_execution": bool(stored.get("temporary_execution", False)),
                    "plan_step": stored.get("plan_step"),
                }
            )
            if len(recent_feedback) >= 5:
                break
        return {
            "active_plans": len(active),
            "pending_reminders": pending_reminders[:5],
            "recent_failures": recent_failures,
            "recent_feedback": recent_feedback,
            "last_action_at": (
                records[0].updated_at.isoformat() if records and records[0].updated_at else None
            ),
        }
    except Exception:
        logger.exception("行动事实收集失败，返回空包")
        return {}


async def run_action_retry_loop():
    """lifespan 维护循环：重试到期的 retryable 行动 + 处理过期计划（action_enabled 门控）。"""

    async def _tick():
        if get_settings().action_enabled:
            await _process_due_retries()
            _expire_planned()

    await run_worker_loop(
        "action retry loop",
        _tick,
        get_settings().action_maintenance_interval_seconds,
    )


async def _process_due_retries():
    try:
        records = action_repository.list_retryable(_now(), limit=50)
        settings = get_settings()
        for record in records:
            try:
                record, plan, snapshot = _rebuild_plan(record, settings)
                if plan is None:
                    continue
                ctx = ExecutionContext(
                    user_id=record.user_id, character_id=record.character_id,
                    record_id=record.id, now=_now(), settings=settings,
                )
                result = await execute_plan(
                    record,
                    plan,
                    ctx,
                    permission_snapshot=_build_permission_snapshot(record.user_id, settings),
                    tool_context=snapshot.tool_context,
                )
                if record.status != "failed":
                    _apply_feedback(record, result)
            except Exception:
                logger.exception("行动重试失败，保持执行中状态")
    except Exception:
        logger.exception("行动重试扫描失败")


def _expire_planned():
    try:
        records = action_repository.list_planned(_now(), limit=50)
        for record in records:
            if record.scheduled_at is not None and record.scheduled_at <= _now() - timedelta(
                hours=get_settings().action_plan_expiry_hours
            ):
                record.status = "cancelled"
                record.gate_reason = "expired"
                record.updated_at = _now()
                action_repository.save_record(record)
    except Exception:
        logger.exception("行动过期扫描失败")
    _expire_pending_confirmations()
    _recover_stale_executing()


def _recover_stale_executing() -> int:
    """architecture §11.4：孤儿 executing 超时置 failed，避免永久非终态。"""
    settings = get_settings()
    if not getattr(settings, "action_execution_enabled", False):
        return 0
    try:
        cutoff = _now() - timedelta(minutes=settings.action_executing_timeout_minutes)
        records = action_repository.list_stale_executing(cutoff, limit=50)
        recovered = 0
        for record in records:
            next_status = transition_action("executing", "step_permanent_failed") or "failed"
            record.status = next_status
            record.gate_reason = "timeout"
            if record.attempt < settings.action_retry_max_attempts:
                record.next_retry_at = _now() + timedelta(
                    seconds=settings.action_retry_backoff_seconds
                )
            record.updated_at = _now()
            action_repository.save_record(record)
            recovered += 1
        if recovered:
            logger.info("孤儿 executing 恢复：%d 条", recovered)
        return recovered
    except Exception:
        logger.exception("孤儿 executing 恢复扫描失败")
        return 0


def _expire_pending_confirmations() -> int:
    """TOOL-005 过期清理挂接点：复用既有 action 计划过期维护步（不新增维护步）。

    挂接在 `_expire_planned` 函数体内（life_loop 维护步序列零改动）；清理失败仅记日志，
    下一轮维护重试，不影响行动过期扫描。
    """
    settings = get_settings()
    if not (
        getattr(settings, "tool_system_enabled", False)
        and getattr(settings, "tool_permission_enabled", False)
    ):
        return 0
    try:
        expired = get_confirmation_service(settings).expire_due(_now())
    except Exception:
        logger.exception("确认请求过期清理失败，下轮维护重试")
        return 0
    if expired:
        logger.info("过期确认请求已清理：%d 条", expired)
    return expired


def _rebuild_plan(record: ActionRecord, settings):
    """重试重建计划：返回（记录，计划，快照）——快照供 TOOL-007 世界事实复用。"""
    intent = ActionIntent.model_validate(record.intent)
    snapshot = _build_snapshot(record.user_id, settings)
    plan = assemble_plan(intent, snapshot, _now(), goal_id=record.goal_id)
    if plan is None:
        record.status = "failed"
        record.gate_reason = "capability_unavailable"
        record.updated_at = _now()
        action_repository.save_record(record)
        return record, None, snapshot
    return record, plan, snapshot
