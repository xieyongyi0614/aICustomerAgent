"""V2.6.0 System Integration：Planning/World/Relationship/Memory 四路接线（architecture.md §10）。"""

import logging
from datetime import datetime
from typing import Any

from app.core.settings import get_settings
from app.models.action import (
    Action,
    ActionEffect,
    ActionIntent,
    ActionRecord,
    ActionResult,
)
from app.models.plan import PlanStepOutcome
from app.repositories import action_repository
from app.services.action import manager, result as result_service

logger = logging.getLogger(__name__)

EFFECT_CHANNELS = ("world", "memory", "relationship", "note")


def _now() -> datetime:
    return datetime.now()


def feedback_enabled() -> bool:
    settings = get_settings()
    return bool(
        getattr(settings, "v26_action_execution_enabled", False)
        and getattr(settings, "v26_action_feedback_enabled", False)
    )


def create_from_plan_intent(
    intent: ActionIntent,
    *,
    user_id: str,
    session_id: str | None = None,
    goal_id: str | None = None,
    plan_step: str | None = None,
    priority: int = 100,
) -> Action:
    action = manager.create(
        user_id=user_id,
        action_type=intent.action_type,
        params=dict(intent.params or {}),
        source="plan",
        session_id=session_id,
        goal_id=goal_id,
        intent=intent,
        priority=priority,
    )
    if plan_step:
        record = action_repository.get_record(action.id)
        if record is not None:
            record.intent = dict(record.intent or {})
            record.intent["plan_step"] = plan_step
            action_repository.save_record(record)
            action = manager.query(action.id)
    return action


async def execute_plan_action(
    action: Action, *, session_id: str | None = None
) -> ActionResult | None:
    from app.application import action_engine

    intent_data = None
    record = action_repository.get_record(action.id)
    if record is not None:
        intent_data = record.intent
    if not intent_data:
        intent = ActionIntent(
            action_type=action.type,
            confidence="confident",
            params=dict(action.parameters or {}),
            dedupe_key=action.dedupe_key,
        )
    else:
        intent = ActionIntent.model_validate(intent_data)
    user_id = action.target or (record.user_id if record else "unknown")
    executed = await action_engine.run_action_planning(
        user_id=user_id,
        intent=intent,
        session_id=session_id,
        goal_id=action.goal_id,
        source="plan",
    )
    if executed is None or executed.result is None:
        return None
    return ActionResult.model_validate(executed.result)


def to_plan_step_outcome(
    result: ActionResult,
    *,
    action_id: str,
    step_index: int = 1,
    tool_id: str = "",
    duration_ms: int = 0,
) -> PlanStepOutcome:
    status = result.status
    if status == "timeout":
        status = "failed"
    if status == "succeeded":
        outcome_status = "succeeded"
    else:
        outcome_status = "failed"
    observations = {
        k: result.observations[k]
        for k in ("world_event_id", "memory_id", "entity_id", "note")
        if k in result.observations
    }
    return PlanStepOutcome(
        step_index=step_index,
        status=outcome_status,  # type: ignore[arg-type]
        at=result.created_at or _now(),
        action_id=action_id,
        tool_id=tool_id,
        failure_kind=result.failure_kind,
        effects=[effect.model_dump() for effect in result.effects],
        observations=observations,
        duration_ms=duration_ms,
    )


def route_effects(result: ActionResult) -> dict[str, list[ActionEffect]]:
    routed: dict[str, list[ActionEffect]] = {kind: [] for kind in EFFECT_CHANNELS}
    for effect in result.effects:
        if effect.kind in routed:
            routed[effect.kind].append(effect)
    return routed


def is_temporary_execution(record: ActionRecord) -> bool:
    policy = get_settings().action_memory_policy()
    row = policy.get(record.action_type)
    return not (row and row.get("deposit"))


def apply_result_feedback(record: ActionRecord, result: ActionResult) -> dict[str, Any]:
    """统一反馈入口：四通道回写 + 三面反馈投影。复用 integrate_result，不新建机制。"""
    from app.application import action_engine

    if not feedback_enabled():
        action_engine.integrate_result(record, result)
        routed = route_effects(result)
        return {
            "mode": "legacy",
            "channels": {k: len(v) for k, v in routed.items()},
        }

    enriched = result_service.ensure_result_identity(result, record.id)
    routed = route_effects(enriched)
    enhanced = ActionResult(
        id=enriched.id,
        action_id=enriched.action_id,
        status=enriched.status,
        effects=enriched.effects,
        error=enriched.error,
        failure_kind=enriched.failure_kind,
        output=enriched.output,
        metadata=enriched.metadata,
        observations=enriched.observations,
        created_at=enriched.created_at or _now(),
    )
    action_engine.integrate_result(record, enhanced)
    payload = result_service.feedback_payload(enhanced)
    payload["temporary_execution"] = is_temporary_execution(record)
    payload["plan_step"] = (record.intent or {}).get("plan_step")
    logger.info(
        "Action Feedback action_id=%s status=%s kinds=%s",
        record.id,
        enhanced.status,
        payload.get("feedback_kinds"),
    )
    return {
        "mode": "v26",
        "feedback": payload,
        "channels": {k: len(v) for k, v in routed.items()},
    }


def world_effects_pending(result: ActionResult) -> list[ActionEffect]:
    return route_effects(result)["world"]


def relationship_effects_pending(result: ActionResult) -> list[ActionEffect]:
    return route_effects(result)["relationship"]


def memory_effects_pending(result: ActionResult) -> list[ActionEffect]:
    return route_effects(result)["memory"]
