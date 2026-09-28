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

_SHARED_ROOMS = frozenset(
    {
        "home",
        "home.kitchen",
        "home.living_room",
        "home.dining_area",
    }
)


class _SyntheticObject:
    """轮内 CREATE 的可引用替身；仅 WorkingView 使用。"""

    __slots__ = (
        "id",
        "name",
        "aliases",
        "category",
        "quantity",
        "consumable",
        "status",
        "location_id",
    )

    def __init__(
        self,
        id: str,
        name: str,
        category: str,
        quantity: float,
        location_id: str | None = None,
    ):
        self.id = id
        self.name = name
        self.aliases: list[str] = []
        self.category = category
        self.quantity = quantity
        self.consumable = True
        self.status = ObjectStatus.ACTIVE
        self.location_id = location_id


def _is_active(obj) -> bool:
    status = getattr(obj, "status", None)
    if status is None:
        return True
    if isinstance(status, ObjectStatus):
        return status == ObjectStatus.ACTIVE
    value = getattr(status, "value", status)
    return value == ObjectStatus.ACTIVE or value == "active"


def _room_cluster(location_id: str) -> str:
    parts = location_id.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return location_id


def _is_reachable(role_location: str | None, object_location: str | None) -> bool:
    """默认宽松：缺坐标放行；同址/祖先子孙/同簇/共享生活区互相可达。"""
    if not role_location or not object_location:
        return True
    if role_location == object_location:
        return True
    if object_location.startswith(role_location + ".") or role_location.startswith(
        object_location + "."
    ):
        return True
    role_room = _room_cluster(role_location)
    object_room = _room_cluster(object_location)
    if role_room == object_room:
        return True
    if role_room in _SHARED_ROOMS and object_room in _SHARED_ROOMS:
        return True
    return False


class WorkingView:
    def __init__(self, objects: list, entity_limit: int):
        self.objects: list = list(objects)
        self.remaining_quantity: dict[str, float] = {
            obj.id: obj.quantity for obj in objects
        }
        self.id_to_obj: dict[str, object] = {obj.id: obj for obj in objects}
        self.created_entities: list[dict] = []
        self.location_overrides: dict[str, str] = {}
        self.entity_limit = entity_limit
        self.active_count = len(objects)
        self.accepted_dedupes: set[str] = set()

    def find_object(self, name: str):
        matches = self.find_matches(name)
        return matches[0] if len(matches) == 1 else None

    def find_matches(self, name: str) -> list:
        matches = []
        for obj in self.objects:
            aliases = getattr(obj, "aliases", None) or []
            if obj.name == name or name in aliases:
                matches.append(obj)
        return matches

    def resolve(self, name: str) -> tuple[object | None, str | None]:
        matches = self.find_matches(name)
        if not matches:
            return None, WorldActionReason.OBJECT_NOT_FOUND
        if len(matches) > 1:
            return None, WorldActionReason.AMBIGUOUS_TARGET
        return matches[0], None

    def find_object_by_id(self, obj_id: str):
        return self.id_to_obj.get(obj_id)

    def register_created(
        self,
        synthetic_id: str,
        name: str,
        category: str,
        quantity: float,
        location_id: str | None = None,
    ):
        obj = _SyntheticObject(
            id=synthetic_id,
            name=name,
            category=category,
            quantity=quantity,
            location_id=location_id,
        )
        self.created_entities.append(
            {
                "id": synthetic_id,
                "name": name,
                "category": category,
                "quantity": quantity,
            }
        )
        self.objects.append(obj)
        self.id_to_obj[synthetic_id] = obj
        self.remaining_quantity[synthetic_id] = quantity
        self.active_count += 1

    def has_active_named(self, name: str) -> bool:
        for obj in self.find_matches(name):
            if _is_active(obj):
                return True
        return False

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


def _check_consume(
    action: WorldAction,
    wv: WorkingView,
    role_location: str | None,
) -> str | None:
    if action.quantity is None or action.quantity <= 0:
        return WorldActionReason.INVALID_QUANTITY

    obj, resolve_error = wv.resolve(action.target.name)
    if resolve_error:
        return resolve_error
    if not _is_active(obj):
        return WorldActionReason.OBJECT_NOT_FOUND

    if not obj.consumable:
        return WorldActionReason.NOT_CONSUMABLE

    object_location = wv.location_overrides.get(obj.id, getattr(obj, "location_id", None))
    if not _is_reachable(role_location, object_location):
        return WorldActionReason.LOCATION_UNREACHABLE

    remaining = wv.remaining_quantity.get(obj.id, obj.quantity)
    if remaining < action.quantity:
        return WorldActionReason.INSUFFICIENT_QUANTITY

    action.target.object_id = obj.id
    return None


def _check_create(
    action: WorldAction,
    wv: WorkingView,
    role_location: str | None,
) -> str | None:
    if wv.active_count >= wv.entity_limit:
        return WorldActionReason.ENTITY_LIMIT

    if wv.has_active_named(action.target.name):
        return WorldActionReason.DUPLICATE_ENTITY

    if action.target.location_id and action.target.location_id not in HOME_LOCATIONS:
        return WorldActionReason.LOCATION_UNRESOLVED

    if action.target.location_id and not _is_reachable(
        role_location, action.target.location_id
    ):
        return WorldActionReason.LOCATION_UNREACHABLE

    return None


def _check_move(
    action: WorldAction,
    wv: WorkingView,
    role_location: str | None,
) -> str | None:
    obj, resolve_error = wv.resolve(action.target.name)
    if resolve_error:
        return resolve_error
    if not _is_active(obj):
        return WorldActionReason.OBJECT_NOT_FOUND

    if action.target.location_id is None:
        return WorldActionReason.LOCATION_UNRESOLVED

    if action.target.location_id not in HOME_LOCATIONS:
        return WorldActionReason.LOCATION_UNRESOLVED

    current_loc = wv.location_overrides.get(obj.id, getattr(obj, "location_id", None))
    if not _is_reachable(role_location, current_loc):
        return WorldActionReason.LOCATION_UNREACHABLE

    if current_loc == action.target.location_id:
        return WorldActionReason.NO_OP

    action.target.object_id = obj.id
    return None


def validate_actions(
    candidates: list[WorldAction],
    world_id: str | None = None,
    user_id: str | None = None,
    recent_dedupe_keys: set[str] | None = None,
) -> list[ValidationResult]:
    settings = get_settings()

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
        role_location = getattr(world, "current_location", None)
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
            error_reason = _check_consume(action, wv, role_location)
        elif action.action_type == "CREATE":
            error_reason = _check_create(action, wv, role_location)
        elif action.action_type == "MOVE":
            error_reason = _check_move(action, wv, role_location)

        if error_reason:
            action.transition(ActionTransitionEvent.VALIDATE_REJECT)
            results.append(ValidationResult(action, "rejected", error_reason))
            continue

        action.transition(ActionTransitionEvent.VALIDATE_PASS)

        if action.action_type == "CONSUME" and action.target.object_id:
            wv.deduct_quantity(action.target.object_id, action.quantity or 1.0)
        elif action.action_type == "CREATE":
            created_location = action.target.location_id or role_location
            wv.register_created(
                synthetic_id=f"syn_{action.action_id}",
                name=action.target.name,
                category=action.target.category or "misc",
                quantity=action.quantity or 1.0,
                location_id=created_location,
            )
        elif action.action_type == "MOVE" and action.target.object_id:
            if action.target.location_id:
                wv.update_location(action.target.object_id, action.target.location_id)

        if action.dedupe_key:
            dedupe_keys.add(action.dedupe_key)
            wv.accepted_dedupes.add(action.dedupe_key)

        results.append(ValidationResult(action, "validated"))

    return results
