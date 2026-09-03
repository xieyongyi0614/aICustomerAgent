"""V9 ActionEngine（execution-engine.md §1）。

行动域唯一编排器：create_record → evaluate_gates → assemble_plan →
execute_plan → integrate_result。全部发生在 post_process 第 9 步（per-user 写锁内）
或重试维护循环中。只做调度与容错，检出/闸门/执行逻辑在 services。
"""

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
    action_repository.save_record(record)

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
