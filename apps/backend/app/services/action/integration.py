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
    return manager.create(
        user_id=user_id,
        action_type=intent.action_type,
        params=dict(intent.params or {}),
        source="plan",
        session_id=session_id,
        goal_id=goal_id,
        intent=intent,
        priority=priority,
        plan_step=plan_step,
    )


async def execute_plan_action(
    action: Action, *, session_id: str | None = None
) -> ActionResult | None:
    return await manager.execute(action.id, session_id=session_id)


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
    """统一反馈入口：四通道回写 + 三面反馈投影。复用 integrate_result，不新建机制。

    V2.6.1：主路径唯一入口。feedback off 时仅委托 integrate_result；on 时在四通道
    落库后把 `feedback_kinds` / `temporary_execution` / `plan_step` 扩写进 `record.result`。
    """
    from app.application import action_engine

    action_engine.integrate_result(record, result)

    if not feedback_enabled():
        routed = route_effects(result)
        return {
            "mode": "legacy",
            "channels": {k: len(v) for k, v in routed.items()},
        }

    stored = record.result if isinstance(record.result, dict) else {}
    effects = stored.get("effects") if isinstance(stored.get("effects"), list) else []
    kinds: set[str] = set()
    rebuilt_effects: list[ActionEffect] = []
    for effect in effects:
        if isinstance(effect, dict):
            rebuilt_effects.append(
                ActionEffect(
                    kind=effect.get("kind", "note"),
                    ref=str(effect.get("ref", "")),
                    detail=str(effect.get("detail", "")),
                )
            )
        elif isinstance(effect, ActionEffect):
            rebuilt_effects.append(effect)
    for effect in rebuilt_effects:
        if effect.kind:
            kinds.add(effect.kind)
    for effect in result.effects:
        if effect.kind:
            kinds.add(effect.kind)
    dual = result_service.feedback_payload(
        result.model_copy(update={"effects": rebuilt_effects})
    )
    feedback = dict(stored)
    for key, value in dual.items():
        if key not in feedback:
            feedback[key] = value
    if rebuilt_effects:
        feedback["effects"] = [e.model_dump(mode="json") for e in rebuilt_effects]
    feedback["feedback_kinds"] = sorted(kinds)
    feedback["temporary_execution"] = is_temporary_execution(record)
    feedback["plan_step"] = (record.intent or {}).get("plan_step")
    record.result = feedback
    record.updated_at = _now()
    action_repository.save_record(record)
    logger.info(
        "Action Feedback action_id=%s status=%s kinds=%s",
        record.id,
        feedback.get("status"),
        feedback["feedback_kinds"],
    )
    return {
        "mode": "v26",
        "feedback": feedback,
        "channels": {k: len(v) for k, v in route_effects(result).items()},
    }


def world_effects_pending(result: ActionResult) -> list[ActionEffect]:
    return route_effects(result)["world"]


def relationship_effects_pending(result: ActionResult) -> list[ActionEffect]:
    return route_effects(result)["relationship"]


def memory_effects_pending(result: ActionResult) -> list[ActionEffect]:
    return route_effects(result)["memory"]
