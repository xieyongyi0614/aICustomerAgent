"""Action Mutation（ACTION-004）。

validated WorldAction → applied / failed：唯一真实写库出口，逐条保序执行。
只调用 world_engine 公开写函数；失败不补偿写、不部分扣除；成功后落 character_action 事件。
"""

import logging
import time

from app.services.world import engine_port as world_engine
from app.character.asuna.action import infer_object_category
from app.core.settings import get_settings
from app.models.character_action import (
    ActionTransitionEvent,
    MutationOutcome,
    WorldAction,
    WorldActionReason,
    WorldActionStatus,
)
from app.models.observability import bound_extra
from app.models.world import WorldObject

logger = logging.getLogger(__name__)


def _snapshot_frame(obj: WorldObject | None) -> dict | None:
    if obj is None:
        return None
    return {
        "quantity": obj.quantity,
        "state": obj.state,
        "location_id": obj.location_id,
    }


def _record_trace(
    trace, outcome: MutationOutcome, duration_ms: float, error: str | None = None
) -> None:
    if trace is None:
        return
    try:
        extra, _ = bound_extra(
            {
                "action_id": outcome.action_id,
                "status": outcome.status,
                "engine_fn": outcome.engine_fn,
                "engine_error": outcome.engine_error,
                "object_id": outcome.object_id,
                "name": outcome.name,
                "before": outcome.before,
                "after": outcome.after,
                "world_event_id": outcome.world_event_id,
            },
            get_settings().observability_step_extra_max_chars,
        )
        trace.record(
            "character_action_sync",
            duration_ms,
            status=outcome.status,
            error=error,
            **extra,
        )
    except Exception:
        logger.warning("角色动作 trace 记录失败，忽略")


def _readback_frame(user_id: str, name: str) -> dict | None:
    return _snapshot_frame(world_engine.find_object_by_name(user_id, name))


def _apply_one(action: WorldAction, user_id: str, trace=None) -> MutationOutcome:
    started = time.perf_counter()
    before = None
    after = None
    object_id = None
    engine_fn = None
    engine_error = None
    location_from = None
    location_to = None
    error_text = None
    applied = False

    try:
        if action.action_type == "CREATE":
            engine_fn = "create_object"
            world = world_engine.get_world(user_id)
            location_id = action.target.location_id or (
                world.current_location if world is not None else None
            )
            obj = world_engine.create_object(
                user_id,
                name=action.target.name,
                category=infer_object_category(action.target.name),
                location_id=location_id,
                quantity=action.quantity or 1.0,
            )
            if obj is not None:
                object_id = obj.id
                applied = True
            else:
                engine_error = WorldActionReason.ENGINE_FAILED.value
            after = _readback_frame(user_id, action.target.name) or _snapshot_frame(obj)

        elif action.action_type == "MOVE":
            engine_fn = "move_object"
            before = _snapshot_frame(
                world_engine.find_object_by_name(user_id, action.target.name)
            )
            location_from = (before or {}).get("location_id")
            location_to = action.target.location_id
            obj = world_engine.move_object(
                user_id, action.target.object_id, action.target.location_id
            )
            if obj is not None:
                object_id = obj.id
                applied = True
            else:
                engine_error = WorldActionReason.ENGINE_FAILED.value
            after = _readback_frame(user_id, action.target.name)

        elif action.action_type == "CONSUME":
            engine_fn = "consume_object"
            before = _snapshot_frame(
                world_engine.find_object_by_name(user_id, action.target.name)
            )
            result = world_engine.consume_object(
                user_id, action.target.name, action.quantity or 1.0
            )
            if result.ok:
                object_id = result.object.id
                applied = True
            else:
                engine_error = (
                    result.error.value
                    if result.error
                    else WorldActionReason.ENGINE_FAILED.value
                )
            after = _readback_frame(user_id, action.target.name) or _snapshot_frame(
                result.object
            )

        else:
            engine_error = WorldActionReason.UNSUPPORTED_TYPE.value

        if applied and not engine_error:
            event = world_engine.record_character_action_event(
                user_id,
                action_type=action.action_type,
                target_name=action.target.name,
                quantity=action.quantity,
                object_id=object_id,
                before=before,
                after=after,
                location_from=location_from,
                location_to=location_to,
                dedupe_key=action.dedupe_key,
                session_id=action.turn_ref.session_id,
                turn_id=action.turn_ref.turn_id,
                actor=action.actor,
            )
            if event is not None:
                action.metadata["world_event_id"] = event.id
                action.metadata["world_event_title"] = event.title
    except Exception:
        logger.exception("角色动作执行异常：%s", action.action_id)
        applied = False
        engine_error = WorldActionReason.ENGINE_FAILED.value
        error_text = "engine crashed"

    if applied:
        action.transition(ActionTransitionEvent.ENGINE_OK)
    else:
        action.transition(ActionTransitionEvent.ENGINE_FAIL)
        if error_text is None and engine_error:
            error_text = engine_error

    outcome = MutationOutcome(
        action_id=action.action_id,
        status=action.status.value,
        engine_fn=engine_fn,
        engine_error=engine_error,
        object_id=object_id,
        name=action.target.name,
        before=before,
        after=after,
        world_event_id=action.metadata.get("world_event_id"),
        title=action.metadata.get("world_event_title"),
    )
    _record_trace(
        trace,
        outcome=outcome,
        duration_ms=(time.perf_counter() - started) * 1000,
        error=error_text,
    )
    return outcome


def execute_actions(
    validated_actions: list[WorldAction],
    user_id: str | None = None,
    trace=None,
) -> list[MutationOutcome]:
    """按文本顺序逐条执行 validated 动作；返回与输入等长的结果列表。"""
    if user_id is None:
        return [
            MutationOutcome(action_id=a.action_id, status="failed")
            for a in validated_actions
        ]

    try:
        world = world_engine.ensure_world(user_id)
    except Exception:
        logger.exception("世界不可用，全部判 failed")
        world = None

    outcomes: list[MutationOutcome] = []
    for action in validated_actions:
        if action.status is not WorldActionStatus.VALIDATED:
            outcomes.append(
                MutationOutcome(action_id=action.action_id, status=action.status.value)
            )
            continue
        if world is None:
            action.transition(ActionTransitionEvent.ENGINE_FAIL)
            outcomes.append(
                MutationOutcome(
                    action_id=action.action_id,
                    status="failed",
                    engine_error=WorldActionReason.WORLD_UNAVAILABLE.value,
                )
            )
            continue
        outcomes.append(_apply_one(action, user_id, trace))
    return outcomes
