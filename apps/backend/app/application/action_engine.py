"""V9 ActionEngine（execution-engine.md §1）。

行动域唯一编排器：create_record → evaluate_gates → assemble_plan →
execute_plan → integrate_result。全部发生在 post_process 第 9 步（per-user 写锁内）
或重试维护循环中。只做调度与容错，检出/闸门/执行逻辑在 services。

V2.4.0：`v24_tool_system_enabled` 开启时 `execute_plan` 的步骤执行改走 `ToolExecutor`
（五段短路 + 结果归一），`steps[]` 增量落 `tool_id` / `permission` / `validation` /
`duration_ms`；总闸关闭时执行路径与 V2.3.0 逐字节一致。
"""

import asyncio
import logging
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.action import (
    ActionEffect,
    ActionResult,
    ActionPlan,
    ActionRecord,
    ActionIntent,
    transition_action,
)
from app.models.tool import ToolInvocation
from app.repositories import action_repository
from app.services.action.executor import CapabilityExecutor
from app.services.action.planner import GateSnapshot, assemble_plan, evaluate_gates
from app.services.action.registry import ExecutionContext, get_capability_registry
from app.services.tool.context import ToolContext
from app.services.tool.executor import ToolExecutor, resolve_step_binding
from app.services.tool.health import ToolHealthTracker
from app.services.tool.registry import ToolRegistry, get_tool_registry
from app.application import world_engine
from app.application.worker_loop import run_worker_loop
from app.services.action import memory_bridge, relationship_bridge

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("created", "planned", "executing")
RETRYABLE_FAILURES = ("transient", "timeout")

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


def new_record(intent: ActionIntent, user_id: str, session_id: str | None, source: str = "conversation") -> ActionRecord:
    return ActionRecord(
        id=action_repository.new_record_id(),
        user_id=user_id,
        session_id=session_id,
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
    """装配六闸门快照（读世界现状与既有记录，闸门内零 IO）。"""
    snapshot = GateSnapshot(settings=settings, registry=get_capability_registry(), now=_now())
    snapshot.records = [
        {"dedupe_key": r.dedupe_key, "status": r.status, "created_at": r.created_at}
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
    return snapshot


async def execute_plan(record: ActionRecord, plan: ActionPlan, ctx: ExecutionContext) -> ActionResult:
    """执行计划：step 归一回填 steps/result；重试保留同 Record。"""
    settings = get_settings()
    storage = get_capability_registry()
    executor = CapabilityExecutor(storage, settings.action_execution_timeout_seconds)
    record.status = "executing"
    record.executed_at = _now()
    record.updated_at = _now()
    action_repository.save_record(record)

    tool_registry = get_tool_registry() if settings.v24_tool_system_enabled else None
    if tool_registry is not None:
        return await _execute_plan_via_tools(
            record, plan, ctx, settings, executor, tool_registry
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
            record.status = "failed"
    record.result = result_out.model_dump(mode="json")
    record.updated_at = _now()
    action_repository.save_record(record)
    return result_out


async def _execute_plan_via_tools(
    record: ActionRecord,
    plan: ActionPlan,
    ctx: ExecutionContext,
    settings,
    capability_executor: CapabilityExecutor,
    tool_registry: ToolRegistry,
) -> ActionResult:
    """总闸开启时的执行路径：五段短路 + `steps[]` 新字段（TOOL-003 §2.2、§2.4）。"""
    tool_executor = ToolExecutor(
        tool_registry,
        capability_executor,
        settings=settings,
        health=ToolHealthTracker(tool_registry, settings),
    )
    tool_ctx = ToolContext.from_execution_context(ctx)
    intent = ActionIntent.model_validate(record.intent) if record.intent else plan.intent

    step_dicts: list[dict] = []
    statuses: list[str] = []
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
        execution = await tool_executor.run(
            binding,
            ToolInvocation(
                tool_id=binding.tool_id,
                params=dict(step.params),
                rationale=str(record.intent.get("evidence", "")),
                source=record.source,
                intent=intent,
                goal_id=record.goal_id,
                dedupe_key=record.dedupe_key,
            ),
            tool_ctx,
            index=step.index,
        )
        step_dicts.append(_tool_step_dict(step, execution))
        statuses.append(execution.status)
        if execution.status not in ("succeeded", "failed", "timeout"):
            break

    record.steps = step_dicts
    outcome = next((status for status in statuses if status != "succeeded"), "succeeded")
    if outcome in _TOOL_RECORD_OUTCOMES:
        record.status, record.gate_reason = _TOOL_RECORD_OUTCOMES[outcome]
        result_out = _tool_action_result(record, outcome, step_dicts)
    else:
        result_out = _settle_executed_record(record, settings, step_dicts)
    record.result = result_out.model_dump(mode="json")
    record.updated_at = _now()
    action_repository.save_record(record)
    return result_out


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
        record.status = "failed"
    return result_out


def _tool_action_result(
    record: ActionRecord, outcome: str, step_dicts: list[dict]
) -> ActionResult:
    """闸门段失败（unavailable / denied / invalid）与待确认行动的 ActionResult 投影。"""
    step_result = dict(step_dicts[0].get("result") or {}) if step_dicts else {}
    detail = step_result.get("error") or _TOOL_RECORD_OUTCOMES[outcome][1]
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


def integrate_result(record: ActionRecord, result: ActionResult) -> None:
    """结果整合四通道（execution-engine.md §1）：世界/记忆/关系/note。

    V2.4.0：效果引用读 `steps[].result.effects`（新键）优先，`payload` 旧键兜底——
    兼容窗口 ≥ 一个版本，Flag off 时等价于 V9 原路径。
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

    record.result = ActionResult(
        status=result.status, effects=effects, error=result.error, failure_kind=result.failure_kind
    ).model_dump(mode="json")

    if settings.v2_action_outbox_enabled:
        _integrate_via_outbox(record)
        return

    if settings.action_enabled:
        memory_payload = memory_bridge.deliver_action_memory(record, record.user_id, record.character_id)
        if memory_payload:
            _append_effect(record, "memory", memory_payload.get("memory_id", ""), "已记住")
        relationship_bridge.deliver_action_signal(record, record.user_id)

    record.updated_at = _now()
    action_repository.save_record(record)


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
    result = await execute_plan(record, plan, ctx)
    if record.status != "failed":
        integrate_result(record, result)
    else:
        record.updated_at = _now()
        action_repository.save_record(record)
    return record


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
        return {
            "active_plans": len(active),
            "pending_reminders": pending_reminders[:5],
            "recent_failures": recent_failures,
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
                record, plan = _rebuild_plan(record, settings)
                if plan is None:
                    continue
                ctx = ExecutionContext(
                    user_id=record.user_id, character_id=record.character_id,
                    record_id=record.id, now=_now(), settings=settings,
                )
                result = await execute_plan(record, plan, ctx)
                if record.status != "failed":
                    integrate_result(record, result)
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


def _rebuild_plan(record: ActionRecord, settings):
    intent = ActionIntent.model_validate(record.intent)
    snapshot = _build_snapshot(record.user_id, settings)
    plan = assemble_plan(intent, snapshot, _now(), goal_id=record.goal_id)
    if plan is None:
        record.status = "failed"
        record.gate_reason = "capability_unavailable"
        record.updated_at = _now()
        action_repository.save_record(record)
        return record, None
    return record, plan
