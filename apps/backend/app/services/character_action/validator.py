"""Action Validation（ACTION-003）。

候选 WorldAction → validated / rejected(reason)：确定性裁决，失败零变更。
零写库：只读快照 + 内存 Working View。
"""

import logging

from app.character.asuna.world import HOME_LOCATIONS
from app.core.settings import get_settings
from app.models.character_action import (
    WorldAction,
    WorldActionReason,
    ActionTransitionEvent,
)
from app.models.world import ObjectStatus
from app.application.world_engine import ensure_world
from app.repositories import world_repository

logger = logging.getLogger(__name__)


class WorkingView:
    def __init__(self, objects: list, entity_limit: int):
        self.remaining_quantity: dict[str, float] = {
            obj.id: obj.quantity for obj in objects
        }
        self.name_to_obj: dict[str, object] = {obj.name: obj for obj in objects}
        self.id_to_obj: dict[str, object] = {obj.id: obj for obj in objects}
        self.created_entities: list[dict] = []
        self.location_overrides: dict[str, str] = {}
        self.entity_limit = entity_limit
        self.active_count = len(objects)
        self.accepted_dedupes: set[str] = set()

    def find_object(self, name: str):
        return self.name_to_obj.get(name)

    def find_object_by_id(self, obj_id: str):
        return self.id_to_obj.get(obj_id)

    def register_created(self, synthetic_id: str, name: str, category: str, quantity: float):
        self.created_entities.append({
            "id": synthetic_id,
            "name": name,
            "category": category,
            "quantity": quantity,
        })
        self.active_count += 1

    def deduct_quantity(self, obj_id: str, quantity: float) -> float:
        current = self.remaining_quantity.get(obj_id, 0.0)
        new_qty = max(0.0, round(current - quantity, 2))
        self.remaining_quantity[obj_id] = new_qty
        return new_qty

    def update_location(self, obj_id: str, location_id: str):
        self.location_overrides[obj_id] = location_id


class ValidationResult:
    __slots__ = ("action", "status", "reason", "detail")

    def __init__(self, action: WorldAction, status: str, reason: str | None = None, detail: str = ""):
        self.action = action
        self.status = status
        self.reason = reason
        self.detail = detail


def _check_consume(action: WorldAction, wv: WorkingView) -> str | None:
    if action.quantity is None or action.quantity <= 0:
        return WorldActionReason.INVALID_QUANTITY

    obj = wv.find_object(action.target.name)
    if obj is None:
        return WorldActionReason.OBJECT_NOT_FOUND

    if not obj.consumable:
        return WorldActionReason.NOT_CONSUMABLE

    if obj.status != ObjectStatus.ACTIVE:
        return WorldActionReason.OBJECT_NOT_FOUND

    remaining = wv.remaining_quantity.get(obj.id, obj.quantity)
    if remaining < action.quantity:
        return WorldActionReason.INSUFFICIENT_QUANTITY

    action.target.object_id = obj.id
    return None


def _check_create(action: WorldAction, wv: WorkingView) -> str | None:
    if wv.active_count >= wv.entity_limit:
        return WorldActionReason.ENTITY_LIMIT

    if action.target.location_id and action.target.location_id not in HOME_LOCATIONS:
        return WorldActionReason.LOCATION_UNRESOLVED

    return None


def _check_move(action: WorldAction, wv: WorkingView) -> str | None:
    obj = wv.find_object(action.target.name)
    if obj is None:
        return WorldActionReason.OBJECT_NOT_FOUND

    if obj.status != ObjectStatus.ACTIVE:
        return WorldActionReason.OBJECT_NOT_FOUND

    action.target.object_id = obj.id

    if action.target.location_id is None:
        return WorldActionReason.LOCATION_UNRESOLVED

    if action.target.location_id not in HOME_LOCATIONS:
        return WorldActionReason.LOCATION_UNRESOLVED

    current_loc = wv.location_overrides.get(obj.id, obj.location_id)
    if current_loc == action.target.location_id:
        return WorldActionReason.NO_OP

    return None


def validate_actions(
    candidates: list[WorldAction],
    world_id: str | None = None,
    user_id: str | None = None,
    recent_dedupe_keys: set[str] | None = None,
) -> list[ValidationResult]:
    settings = get_settings()
    if not settings.world_enabled:
        for action in candidates:
            action.transition(ActionTransitionEvent.VALIDATE_REJECT)
        return [ValidationResult(a, "rejected", WorldActionReason.DISABLED) for a in candidates]

    try:
        if user_id:
            world = ensure_world(user_id)
        else:
            world = None

        if world is None:
            for action in candidates:
                action.transition(ActionTransitionEvent.VALIDATE_REJECT)
            return [ValidationResult(a, "rejected", WorldActionReason.WORLD_UNAVAILABLE) for a in candidates]

        objects = world_repository.list_objects(world.world_id)
        wv = WorkingView(objects, settings.world_active_entities_limit)
    except Exception:
        logger.exception("快照装配失败，全部判 WORLD_UNAVAILABLE")
        for action in candidates:
            action.transition(ActionTransitionEvent.VALIDATE_REJECT)
        return [ValidationResult(a, "rejected", WorldActionReason.WORLD_UNAVAILABLE) for a in candidates]

    dedupe_keys = set(recent_dedupe_keys) if recent_dedupe_keys else set()
    results: list[ValidationResult] = []

    for action in candidates:
        if action.dedupe_key and action.dedupe_key in dedupe_keys:
            action.transition(ActionTransitionEvent.VALIDATE_REJECT)
            results.append(ValidationResult(action, "rejected", WorldActionReason.DUPLICATE))
            continue

        if action.action_type not in ("CREATE", "MOVE", "CONSUME"):
            action.transition(ActionTransitionEvent.VALIDATE_REJECT)
            results.append(ValidationResult(action, "rejected", WorldActionReason.UNSUPPORTED_TYPE))
            continue

        error_reason = None
        if action.action_type == "CONSUME":
            error_reason = _check_consume(action, wv)
        elif action.action_type == "CREATE":
            error_reason = _check_create(action, wv)
        elif action.action_type == "MOVE":
            error_reason = _check_move(action, wv)

        if error_reason:
            action.transition(ActionTransitionEvent.VALIDATE_REJECT)
            results.append(ValidationResult(action, "rejected", error_reason))
            continue

        action.transition(ActionTransitionEvent.VALIDATE_PASS)

        if action.action_type == "CONSUME" and action.target.object_id:
            wv.deduct_quantity(action.target.object_id, action.quantity or 1.0)
        elif action.action_type == "CREATE":
            wv.register_created(
                synthetic_id=f"syn_{action.action_id}",
                name=action.target.name,
                category=action.target.category or "misc",
                quantity=action.quantity or 1.0,
            )
        elif action.action_type == "MOVE" and action.target.object_id:
            if action.target.location_id:
                wv.update_location(action.target.object_id, action.target.location_id)

        if action.dedupe_key:
            dedupe_keys.add(action.dedupe_key)
            wv.accepted_dedupes.add(action.dedupe_key)

        results.append(ValidationResult(action, "validated"))

    return results
