"""V9 ActionEngine（execution-engine.md §1）。

行动域唯一编排器：create_record → evaluate_gates → assemble_plan →
execute_plan → integrate_result。全部发生在 post_process 第 9 步（per-user 写锁内）
或重试维护循环中。只做调度与容错，检出/闸门/执行逻辑在 services。
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
from app.repositories import action_repository
from app.services.action.executor import CapabilityExecutor
from app.services.action.planner import GateSnapshot, assemble_plan, evaluate_gates
from app.services.action.registry import ExecutionContext, get_capability_registry

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("created", "planned", "executing")
RETRYABLE_FAILURES = ("transient", "timeout")


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
        from app.application import world_engine

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

def _append_effect(record: ActionRecord, kind: str, ref: str, detail: str) -> None:
    result = ActionResult(**record.result) if record.result else ActionResult(status="succeeded", effects=[])
    result.effects.append(ActionEffect(kind=kind, ref=ref, detail=detail[:200]))
    record.result = result.model_dump(mode="json")


def integrate_result(record: ActionRecord, result: ActionResult) -> None:
    """结果整合四通道（execution-engine.md §1）：世界/记忆/关系/note。"""
    settings = get_settings()
    from app.services.action import memory_bridge, relationship_bridge

    effects = list(result.effects)
    if record.status == "succeeded":
        payloads = [(s.get("result") or {}).get("payload", {}) for s in record.steps]
        first_payload = next(iter(payloads)) if payloads else {}
        if record.action_type in ("create_reminder", "cancel_reminder"):
            event_id = first_payload.get("world_event_id")
            if event_id:
                effects.append(ActionEffect(kind="world", ref=event_id, detail=_detail_for(record)))
        if record.action_type == "remember_fact":
            memory_id = first_payload.get("memory_id")
            if memory_id:
                effects.append(ActionEffect(kind="memory", ref=memory_id, detail="已记住"))

    record.result = ActionResult(
        status=result.status, effects=effects, error=result.error, failure_kind=result.failure_kind
    ).model_dump(mode="json")

    if settings.action_enabled:
        memory_payload = memory_bridge.deliver_action_memory(record, record.user_id, record.character_id)
        if memory_payload:
            _append_effect(record, "memory", memory_payload.get("memory_id", ""), "已记住")
        relationship_bridge.deliver_action_signal(record, record.user_id)

    record.updated_at = _now()
    action_repository.save_record(record)


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
    interval = get_settings().action_maintenance_interval_seconds
    while True:
        try:
            if get_settings().action_enabled:
                await _process_due_retries()
                _expire_planned()
        except Exception:
            logger.exception("行动维护循环异常（双保险）")
        await asyncio.sleep(interval)


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
