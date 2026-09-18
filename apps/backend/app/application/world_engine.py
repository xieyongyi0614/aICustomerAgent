"""V8 WorldEngine（architecture.md §2）：世界生命周期与装配编排。

只做调度与容错：世界读写经 world_repository，任何异常仅 log 并降级（None），
聊天与主动链路永不因世界而失败。
"""

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta

from app.character.asuna.world import (
    DEFAULT_HOUSEHOLD,
    HOME_LOCATIONS,
    OBJECT_STATE_MACHINES,
    WORLD_LOCATION_REGISTRY,
)
from app.core.settings import get_settings
from app.models.world import (
    WorldEnvironment as WorldEnvironmentModel,
    ConsumeError,
    ConsumeResult,
    EventImportance,
    EventSource,
    EventStatus,
    ObjectStatus,
    StateSnapshot,
    World,
    WorldEvent,
    WorldObject,
    WorldTimeMode,
    apply_object_action as apply_machine_action,
    bounded_notes,
    object_default_portions,
    object_initial_state,
    part_of_day,
)
from app.repositories import world_repository
from app.services.world.locations import build_location_context
from app.services.world.time_provider import TimeProvider
from app.application.worker_loop import run_worker_loop
from app.models.observability import bound_extra
from app.services.world.context_selector import (
    build_world_context,
    environment_lighting_suggestion,
    recent_world_changes_from_events,
)
from app.services.world.interpreter import interpret
from app.services.world.memory_bridge import materialize_event_memory
from app.services.world import movement
from app.services.world.time_advancer import advance_world_time

logger = logging.getLogger(__name__)

_default_provider = TimeProvider()

CONSUME_ACTIONS = {"eat"}


def find_object_by_name(user_id: str, name: str) -> WorldObject | None:
    """按名称/别名匹配活跃实体；未命中返回 None（解释器宁缺毋滥）。"""
    try:
        world = get_world(user_id)
        if world is None:
            return None
        for obj in world_repository.list_objects(world.world_id):
            if obj.name == name or name in obj.aliases:
                return obj
        return None
    except Exception:
        logger.exception("世界实体查找失败")
        return None


def move_object(user_id: str, object_id: str, location_id: str) -> WorldObject | None:
    try:
        world = ensure_world(user_id)
        if world is None or location_id not in WORLD_LOCATION_REGISTRY:
            return None
        obj = world_repository.get_object(world.world_id, object_id)
        if obj is None or obj.status is not ObjectStatus.ACTIVE:
            return None
        obj.location_id = location_id
        obj.last_action_at = datetime.now()
        world_repository.save_object(obj)
        return obj
    except Exception:
        logger.exception("世界实体移动失败")
        return None


def apply_object_action(
    user_id: str, object_id: str, action: str, portions: float | None = None
) -> WorldObject | None:
    """Used/Changed：状态机迁移 + 消耗类动作扣减数量；非法迁移返回 None（不造事实）。"""
    try:
        world = get_world(user_id)
        if world is None:
            return None
        obj = world_repository.get_object(world.world_id, object_id)
        if obj is None or obj.status is not ObjectStatus.ACTIVE:
            return None
        new_state = apply_machine_action(
            OBJECT_STATE_MACHINES, obj.category, obj.state, action
        )
        if new_state is None:
            return None
        obj.state = new_state
        if action in CONSUME_ACTIONS:
            portion = object_default_portions(OBJECT_STATE_MACHINES, obj.category)
            amount = (portions or 1) / max(portion, 1)
            obj.quantity = round(max(0.0, obj.quantity - amount), 2)
        if obj.quantity <= 0:
            obj.status = ObjectStatus.DESTROYED
        obj.last_action_at = datetime.now()
        world_repository.save_object(obj)
        return obj
    except Exception:
        logger.exception("世界实体状态迁移失败")
        return None


def discard_object(user_id: str, object_id: str) -> WorldObject | None:
    obj = apply_object_action(user_id, object_id, "discard")
    if obj is not None:
        obj.status = ObjectStatus.DESTROYED
        try:
            world_repository.save_object(obj)
        except Exception:
            logger.exception("世界实体丢弃落库失败")
            return None
    return obj


def _find_inventory_object(world: World | None, ref: str) -> WorldObject | None:
    """按 id 或名称/别名解析活跃库存物品；未命中返回 None。"""
    if world is None:
        return None
    by_id = world_repository.get_object(world.world_id, ref)
    if by_id is not None and by_id.status is ObjectStatus.ACTIVE:
        return by_id
    for obj in world_repository.list_objects(world.world_id):
        if obj.name == ref or ref in obj.aliases:
            return obj
    return None


def consume_object(
    user_id: str, object_ref: str, quantity: float
) -> ConsumeResult:
    """统一 Consume：按 consumable 字段 + 数量规则扣减；失败不部分扣除，返回结构化错误码。"""
    try:
        world = get_world(user_id)
        obj = _find_inventory_object(world, object_ref)
        if world is None or obj is None:
            return ConsumeResult(ok=False, error=ConsumeError.OBJECT_NOT_FOUND)
        if not obj.consumable:
            return ConsumeResult(ok=False, error=ConsumeError.NOT_CONSUMABLE, object=obj)
        if quantity is None or quantity <= 0:
            return ConsumeResult(ok=False, error=ConsumeError.INVALID_QUANTITY, object=obj)
        if obj.quantity < quantity:
            return ConsumeResult(
                ok=False,
                error=ConsumeError.INSUFFICIENT_QUANTITY,
                object=obj,
                previous_quantity=obj.quantity,
            )
        previous = obj.quantity
        remaining = max(0.0, round(obj.quantity - quantity, 2))
        obj.quantity = remaining
        if remaining == 0:
            obj.state = "empty"
        obj.last_action_at = datetime.now()
        obj.updated_at = datetime.now()
        world_repository.save_object(obj)
        return ConsumeResult(ok=True, object=obj, previous_quantity=previous)
    except Exception:
        logger.exception("世界物品消耗失败")
        return ConsumeResult(ok=False, error=ConsumeError.OBJECT_NOT_FOUND)


def get_objects_by_location(user_id: str, location_id: str) -> list[WorldObject]:
    """返回某位置（含其子位置）的活跃物品清单；只读。"""
    try:
        world = get_world(user_id)
        if world is None:
            return []
        prefix = location_id + "."
        return [
            obj
            for obj in world_repository.list_objects(world.world_id)
            if obj.location_id == location_id or obj.location_id.startswith(prefix)
        ]
    except Exception:
        logger.exception("按地点查询世界物品失败")
        return []


def get_available_consumables(user_id: str) -> list[WorldObject]:
    """可消耗且仍有剩余量的物品清单；只读。"""
    try:
        world = get_world(user_id)
        if world is None:
            return []
        return [
            obj
            for obj in world_repository.list_objects(world.world_id)
            if obj.consumable and obj.quantity > 0
        ]
    except Exception:
        logger.exception("查询可消耗物品失败")
        return []


def _household_missing_defaults(world: World) -> bool:
    """活跃物品清单中是否缺失至少一件默认家庭库存物品（回填判据）。"""
    try:
        names = {obj.name for obj in world_repository.list_objects(world.world_id)}
    except Exception:
        return True
    return any(
        spec["name"] not in names for spec in DEFAULT_HOUSEHOLD["objects"]
    )


def seed_default_household(user_id: str) -> int:
    """幂等播种默认家庭库存；返回本次新建数量。已存在的同名物品不重复。"""
    try:
        world = world_repository.ensure_world(user_id)
        if world is None:
            return 0
        existing = {obj.name for obj in world_repository.list_objects(world.world_id)}
        created = 0
        for spec in DEFAULT_HOUSEHOLD["objects"]:
            if spec["name"] in existing:
                continue
            obj = create_object(
                user_id,
                name=spec["name"],
                category=spec["category"],
                location_id=spec["location_id"],
                quantity=spec["quantity"],
                unit=spec.get("unit", ""),
                consumable=spec.get("consumable", False),
            )
            if obj is not None:
                obj.state = "available"
                obj.last_action_at = datetime.now()
                world_repository.save_object(obj)
                created += 1
        return created
    except Exception:
        logger.exception("默认家庭库存播种失败")
        return 0


def expire_due_objects(user_id: str, now: datetime | None = None) -> int:
    """时间演化（Changed）：expiry_at 到期的活跃物品迁移到 expired，幂等。"""
    try:
        world = get_world(user_id)
        if world is None:
            return 0
        now = now or datetime.now()
        expired = 0
        for obj in world_repository.list_objects(world.world_id):
            expiry_at = obj.properties.get("expiry_at")
            if not expiry_at:
                continue
            try:
                deadline = datetime.fromisoformat(str(expiry_at))
            except ValueError:
                continue
            if deadline > now:
                continue
            new_state = apply_machine_action(
                OBJECT_STATE_MACHINES, obj.category, obj.state, "expire"
            )
            if new_state is None:
                continue
            obj.state = new_state
            obj.last_action_at = now
            world_repository.save_object(obj)
            expired += 1
        return expired
    except Exception:
        logger.exception("世界物品过期检查失败")
        return 0


def get_location_context(user_id: str):
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        return build_location_context(world)
    except Exception:
        logger.exception("世界位置上下文装配失败")
        return None


def build_time_context(user_id: str, provider: TimeProvider | None = None):
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        return (provider or _default_provider).context(world)
    except Exception:
        logger.exception("世界时间上下文装配失败")
        return None


def advance_time(user_id: str, delta, provider: TimeProvider | None = None) -> World | None:
    """simulated/story 模式的显式时间推进；real_sync 为 no-op（世界时钟=真实时钟）。"""
    try:
        world = ensure_world(user_id)
        if world is None or world.time_mode is WorldTimeMode.REAL_SYNC:
            return world
        world = (provider or _default_provider).advance(world, delta)
        world_repository.save_world(world)
        return world
    except Exception:
        logger.exception("世界时间推进失败")
        return None


def ensure_world(user_id: str) -> World | None:
    try:
        existing = world_repository.get_world(user_id)
        world = world_repository.ensure_world(user_id)
        settings = get_settings()
        if (
            world is not None
            and settings.world_enabled
            and settings.world_household_autoseed_enabled
            and (existing is None or _household_missing_defaults(world))
        ):
            seed_default_household(user_id)
        return world
    except Exception:
        logger.exception("世界初始化失败，降级为无世界")
        return None


def get_world(user_id: str) -> World | None:
    try:
        return world_repository.get_world(user_id)
    except Exception:
        logger.exception("世界读取失败，降级为无世界")
        return None


def list_active_objects(user_id: str) -> list[WorldObject]:
    """只读辅助：活跃物品列表（V9 行动闸门 G6 快照用，V8 零修改）。"""
    world = get_world(user_id)
    if world is None:
        return []
    return world_repository.list_objects(world.world_id, status="active")


def list_active_events(user_id: str) -> list[WorldEvent]:
    """只读辅助：活跃事件列表（V9 行动闸门 G6 快照用，V8 零修改）。"""
    world = get_world(user_id)
    if world is None:
        return []
    return world_repository.list_events(
        world.world_id,
        statuses=["scheduled", "active"],
    )


def create_object(
    user_id: str,
    name: str,
    category: str = "misc",
    location_id: str | None = None,
    quantity: float = 1.0,
    aliases: list[str] | None = None,
    unit: str = "",
    consumable: bool | None = None,
    **properties,
) -> WorldObject | None:
    try:
        world = world_repository.ensure_world(user_id)
        if world is None:
            return None
        settings = get_settings()
        if (
            world_repository.count_active_objects(world.world_id)
            >= settings.world_active_entities_limit
        ):
            logger.warning("世界实体数达上限，拒绝新建：%s", user_id)
            return None
        now = datetime.now()
        obj = WorldObject(
            id=world_repository.new_object_id(category),
            world_id=world.world_id,
            name=name,
            aliases=aliases or [],
            category=category,
            location_id=location_id or world.current_location,
            state=object_initial_state(OBJECT_STATE_MACHINES, category),
            quantity=quantity,
            unit=unit or "",
            consumable=(
                consumable
                if consumable is not None
                else category in ("food", "drink")
            ),
            properties=properties,
            status=ObjectStatus.ACTIVE,
            last_action_at=now,
            created_at=now,
            updated_at=now,
        )
        world_repository.save_object(obj)
        return obj
    except Exception:
        logger.exception("世界实体创建失败")
        return None


def set_environment(user_id: str, updated_by: str = "manual", **fields) -> World | None:
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        updates = {key: value for key, value in fields.items() if value is not None}
        updates["updated_by"] = updated_by
        updates["updated_at"] = datetime.now()
        world.environment = world.environment.model_copy(update=updates)
        world_repository.save_world(world)
        return world
    except Exception:
        logger.exception("世界环境更新失败")
        return None


def set_location(user_id: str, location_id: str) -> World | None:
    try:
        if location_id not in WORLD_LOCATION_REGISTRY:
            logger.warning("未知地点，拒绝迁移：%s", location_id)
            return None
        world = ensure_world(user_id)
        if world is None:
            return None
        world.current_location = location_id
        world_repository.save_world(world)
        return world
    except Exception:
        logger.exception("世界位置迁移失败")
        return None


def snapshot(user_id: str, label: str | None = None) -> StateSnapshot | None:
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        now = datetime.now()
        state = {
            "sim_time": world.sim_time.isoformat() if world.sim_time else None,
            "current_location": world.current_location,
            "environment": world.environment.model_dump(mode="json", exclude_none=True),
            "entities": [
                obj.model_dump(mode="json")
                for obj in world_repository.list_objects(world.world_id)
            ],
            "events": [
                event.model_dump(mode="json")
                for event in world_repository.list_events(world.world_id, limit=100)
            ],
        }
        snapshot = StateSnapshot(
            id=world_repository.new_snapshot_id(),
            world_id=world.world_id,
            label=label,
            state=state,
            created_at=now,
        )
        world_repository.save_snapshot(snapshot)
        return snapshot
    except Exception:
        logger.exception("世界快照失败")
        return None


def get_full_state(user_id: str) -> dict | None:
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        return {
            "world": world.model_dump(mode="json"),
            "entities": [
                obj.model_dump(mode="json")
                for obj in world_repository.list_objects(world.world_id)
            ],
            "events": [
                event.model_dump(mode="json")
                for event in world_repository.list_events(world.world_id, limit=100)
            ],
            "snapshots": [
                item.model_dump(mode="json")
                for item in world_repository.list_snapshots(world.world_id, limit=5)
            ],
        }
    except Exception:
        logger.exception("世界全量状态读取失败")
        return None


def _character_action_title(
    action_type: str,
    target_name: str,
    quantity: float | None,
    location_to: str | None,
) -> str:
    if action_type == "CONSUME":
        qty = "" if quantity is None else _format_action_quantity(quantity)
        return f"消耗{target_name}{qty}"
    if action_type == "CREATE":
        return f"做出{target_name}"
    if action_type == "MOVE":
        to_name = WORLD_LOCATION_REGISTRY.get(location_to, {}).get("name") if location_to else None
        return f"{target_name}移到{to_name or location_to}"
    return f"{target_name} {action_type}"


def _format_action_quantity(quantity: float) -> str:
    if quantity == 1:
        return ""
    text = str(int(quantity)) if quantity == int(quantity) else str(quantity)
    return f" ×{text}"


_ACTION_EVENT_IMPORTANCE = {
    "CREATE": EventImportance.NORMAL,
    "CONSUME": EventImportance.LOW,
    "MOVE": EventImportance.LOW,
}


def record_character_action_event(
    user_id: str,
    action_type: str,
    target_name: str,
    quantity: float | None,
    object_id: str | None,
    before: dict | None,
    after: dict | None,
    location_from: str | None,
    location_to: str | None,
    dedupe_key: str,
    session_id: str | None = None,
    turn_id: str | None = None,
    actor: str = "character",
) -> WorldEvent | None:
    """已发生历史落库：status=COMPLETED，source=character；同 dedupe_key 幂等不重复。"""
    try:
        world = ensure_world(user_id)
        if world is None:
            return None

        if dedupe_key:
            for event in world_repository.list_events(
                world.world_id,
                statuses=["completed"],
                limit=50,
                types=["character_action"],
                order="created_at_desc",
            ):
                if event.payload.get("dedupe_key") == dedupe_key:
                    return event

        now = datetime.now()
        event = WorldEvent(
            id=world_repository.new_event_id(),
            world_id=world.world_id,
            type="character_action",
            title=_character_action_title(action_type, target_name, quantity, location_to),
            importance=_ACTION_EVENT_IMPORTANCE.get(action_type, EventImportance.NORMAL),
            status=EventStatus.COMPLETED,
            completed_at=now,
            due_at=None,
            payload={
                "action_type": action_type,
                "actor": actor,
                "target_name": target_name,
                "object_id": object_id,
                "quantity": quantity,
                "before": before,
                "after": after,
                "location_from": location_from,
                "location_to": location_to,
                "dedupe_key": dedupe_key,
                "session_id": session_id,
                "turn_id": turn_id,
            },
            source=EventSource.CHARACTER,
            created_at=now,
            updated_at=now,
        )
        world_repository.save_event(event)
        return event
    except Exception:
        logger.exception("角色动作事件落库失败（不回滚已生效的世界变更）")
        return None


def merge_character_action_notes(user_id: str, cas_lines: list[str]) -> bool:
    """第 9 步尾部：CAS 摘要行追加到 world.notes（幂等、有界）；失败不影响已生效变更。"""
    if not cas_lines:
        return True
    try:
        world = get_world(user_id)
        if world is None:
            return False
        notes = list(world.notes or [])
        existing = set(notes)
        added = [line for line in cas_lines if line not in existing]
        if not added:
            return True
        notes = bounded_notes(
            notes + added,
            max(64, get_settings().world_context_char_budget // 4),
        )
        world.notes = notes
        world_repository.save_world(world)
        return True
    except Exception:
        logger.exception("角色动作摘要写 world.notes 失败（不影响已生效世界变更）")
        return False


_QUOTA_EXEMPT_EVENT_TYPES = (
    "time_marker",
    "calendar_event",
    "world_digest",
    "weather_change",
)
"""时间标记类事件：承载时间轴连续性（日/时段/节气/天气/折叠摘要）。

此类事件条数有天然上限（每天几条）且多为 completed 终态，不占用世界活跃配额；
若与普通事件共享配额，长跑世界会在配额打满后静默丢失追赶语义。
"""

_EVENT_QUOTA_DROPS_TOTAL = 0
_EVENT_QUOTA_DROPS_BY_TYPE: dict[str, int] = {}


def event_quota_drop_snapshot() -> dict:
    """配额丢弃计数快照（观测用）：总量 + 分事件类型。"""
    return {
        "total": _EVENT_QUOTA_DROPS_TOTAL,
        "by_type": dict(_EVENT_QUOTA_DROPS_BY_TYPE),
    }


def reset_event_quota_drop_snapshot() -> None:
    global _EVENT_QUOTA_DROPS_TOTAL
    _EVENT_QUOTA_DROPS_TOTAL = 0
    _EVENT_QUOTA_DROPS_BY_TYPE.clear()


def _periodic_event_drop_metric() -> int:
    """配额丢弃的周期汇总计数：每 10 次上报一次，避免刷日志。"""
    return 10


def create_event(
    user_id: str,
    event_type: str,
    title: str | None = None,
    importance: str = "normal",
    due_at: datetime | None = None,
    source: str = "manual",
    status: str = "scheduled",
    payload: dict | None = None,
    idempotency_key: str | None = None,
) -> WorldEvent | None:
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        settings = get_settings()
        if (
            event_type not in _QUOTA_EXEMPT_EVENT_TYPES
            and world_repository.count_active_events(world.world_id)
            >= settings.world_active_events_limit
        ):
            _record_event_quota_drop(event_type, user_id)
            return None
        now = datetime.now()
        event = WorldEvent(
            id=world_repository.new_event_id(),
            world_id=world.world_id,
            type=event_type,
            title=title or event_type,
            importance=EventImportance(importance),
            status=EventStatus(status),
            due_at=due_at,
            payload=payload or {},
            source=EventSource(source),
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )
        world_repository.save_event(event)
        return event
    except Exception:
        logger.exception("世界事件创建失败")
        return None


def _record_event_quota_drop(event_type: str, user_id: str) -> None:
    """记录被配额拒绝的事件：计数 + 周期汇总日志（可观测，不再静默）。"""
    global _EVENT_QUOTA_DROPS_TOTAL
    _EVENT_QUOTA_DROPS_TOTAL += 1
    _EVENT_QUOTA_DROPS_BY_TYPE[event_type] = (
        _EVENT_QUOTA_DROPS_BY_TYPE.get(event_type, 0) + 1
    )
    interval = _periodic_event_drop_metric()
    if interval > 0 and _EVENT_QUOTA_DROPS_TOTAL % interval == 0:
        logger.warning(
            "世界活跃事件数达上限，累计拒绝 %s 条（user=%s 最近类型=%s 分布=%s）",
            _EVENT_QUOTA_DROPS_TOTAL,
            user_id,
            event_type,
            _EVENT_QUOTA_DROPS_BY_TYPE,
        )
    else:
        logger.info(
            "世界活跃事件数达上限，拒绝新建（user=%s type=%s）", user_id, event_type
        )


def _transition_events_by_type(
    user_id: str, event_type: str, target_status: EventStatus
) -> list[WorldEvent]:
    try:
        world = get_world(user_id)
        if world is None:
            return []
        now = datetime.now()
        changed: list[WorldEvent] = []
        for event in world_repository.list_events(
            world.world_id, statuses=["scheduled", "active"]
        ):
            if event.type != event_type:
                continue
            event.status = target_status
            if target_status is EventStatus.ACTIVE:
                event.started_at = now
            if target_status in (EventStatus.COMPLETED, EventStatus.EXPIRED):
                event.completed_at = now
            event.updated_at = now
            world_repository.save_event(event)
            changed.append(event)
        return changed
    except Exception:
        logger.exception("世界事件状态迁移失败")
        return []


def complete_events_by_type(user_id: str, event_type: str) -> int:
    changed = _transition_events_by_type(user_id, event_type, EventStatus.COMPLETED)
    if get_settings().world_memory_bridge_enabled:
        for event in changed:
            materialize_event_memory(event, user_id)
    return len(changed)


def cancel_events_by_type(user_id: str, event_type: str) -> int:
    return _transition_events_by_type(user_id, event_type, EventStatus.CANCELLED)


def trigger_due_events(user_id: str, now: datetime | None = None) -> int:
    try:
        world = get_world(user_id)
        if world is None:
            return 0
        now = now or datetime.now()
        triggered = 0
        for event in world_repository.list_due_events(world.world_id, now):
            event.status = EventStatus.ACTIVE
            event.started_at = now
            event.updated_at = now
            world_repository.save_event(event)
            triggered += 1
        return triggered
    except Exception:
        logger.exception("世界事件到期触发失败")
        return 0


def expire_stale_events(user_id: str, now: datetime | None = None) -> int:
    """active 超过宽限期的世界事件自动过期（event-system.md §2）。"""
    try:
        world = get_world(user_id)
        if world is None:
            return 0
        settings = get_settings()
        now = now or datetime.now()
        grace = timedelta(hours=settings.world_event_grace_hours)
        expired = 0
        for event in world_repository.list_events(world.world_id, statuses=["active"]):
            anchor = event.started_at or event.due_at
            if anchor is None or now - anchor < grace:
                continue
            event.status = EventStatus.EXPIRED
            event.completed_at = now
            event.updated_at = now
            world_repository.save_event(event)
            expired += 1
            if settings.world_memory_bridge_enabled:
                materialize_event_memory(event, user_id)
        return expired
    except Exception:
        logger.exception("世界事件过期清理失败")
        return 0


def run_turn_update(user_id: str, message: str, trace=None) -> int:
    """post_process 第 8 步（H4）：解释用户消息 → 世界状态迁移 + 到期处理。"""
    settings = get_settings()
    if not settings.world_enabled or not settings.world_interpreter_enabled:
        return 0
    started = time.perf_counter()
    try:
        world = ensure_world(user_id)
        if world is None:
            return 0
        now = _default_provider.now(world)
        entities = world_repository.list_objects(world.world_id)
        events = world_repository.list_events(
            world.world_id, statuses=["scheduled", "active"]
        )
        result = interpret(message, world, entities, events, now)

        applied = 0
        for creation in result.creations:
            if create_object(
                user_id,
                name=creation["name"],
                category=creation.get("category", "misc"),
                quantity=creation.get("quantity", 1.0),
            ) is not None:
                applied += 1
        for object_id, target in result.moves:
            if move_object(user_id, object_id, target) is not None:
                applied += 1
        for object_id, action in result.state_actions:
            if apply_object_action(user_id, object_id, action) is not None:
                applied += 1
        for object_id in result.discards:
            if discard_object(user_id, object_id) is not None:
                applied += 1
        if result.location_move is not None:
            if settings.v23_world_simulation_enabled and settings.v23_scene_expansion_enabled:
                move_result = movement.apply(
                    user_id,
                    result.location_move,
                    source=movement.SOURCE_USER_NARRATIVE,
                    reason="interpreter",
                    now=now,
                )
                if move_result.applied:
                    applied += 1
            elif set_location(user_id, result.location_move) is not None:
                applied += 1
        if result.environment_updates:
            if set_environment(user_id, updated_by="interpreter", **result.environment_updates) is not None:
                applied += 1
        for event_spec in result.events:
            if create_event(
                user_id,
                event_type=event_spec["type"],
                title=event_spec["title"],
                importance=event_spec["importance"],
                due_at=event_spec["due_at"],
                source="user_mention",
            ) is not None:
                applied += 1
        for event_type in result.event_completions:
            applied += complete_events_by_type(user_id, event_type)
        for event_type in result.event_cancellations:
            applied += cancel_events_by_type(user_id, event_type)

        triggered = trigger_due_events(user_id, now)
        expire_due_objects(user_id, now)
        expire_stale_events(user_id, now)

        notes = list(result.notes)
        if triggered:
            notes.append("到点的日子到了")
        refreshed = get_world(user_id)
        if refreshed is not None:
            suggestion = environment_lighting_suggestion(now)
            if (
                suggestion
                and not result.environment_updates.get("lighting")
                and refreshed.environment.lighting is None
                and refreshed.environment.updated_by in (None, "system")
            ):
                refreshed.environment = refreshed.environment.model_copy(
                    update={
                        "lighting": suggestion,
                        "updated_by": "system",
                        "updated_at": datetime.now(),
                    }
                )
                applied += 1
            refreshed.notes = bounded_notes(
                notes, max(64, settings.world_context_char_budget // 4)
            )
            world_repository.save_world(refreshed)

        if trace is not None:
            trace.record(
                "world_update",
                (time.perf_counter() - started) * 1000,
                "ok",
                applied=applied,
            )
        return applied
    except Exception:
        logger.exception("世界更新失败，本轮零迁移")
        if trace is not None:
            trace.record("world_update", 0.0, "error", error="world update failed")
        return 0



def build_context(user_id: str, session_id: str | None = None, trace=None):
    """每 turn 一次的世界切片装配（H1）：只读、有界、失败降级 None。"""
    if not get_settings().world_enabled:
        return None
    started = time.perf_counter()
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        time_ctx = _default_provider.context(world)
        entities = world_repository.list_objects(world.world_id)
        events = world_repository.list_events(
            world.world_id, statuses=["scheduled", "active", "completed"], limit=20
        )
        settings = get_settings()
        change_events = None
        if settings.character_action_sync_enabled:
            try:
                change_events = world_repository.list_events(
                    world.world_id,
                    statuses=["completed"],
                    limit=50,
                    types=["character_action"],
                    order="created_at_desc",
                )
            except Exception:
                logger.exception("角色动作事件查询失败，最近世界变化置空")
                change_events = []
        context = build_world_context(
            world,
            entities,
            events,
            time_ctx,
            nearby_limit=settings.world_nearby_objects_limit,
            events_limit=settings.world_salient_events_limit,
            change_events=change_events,
            changes_limit=settings.character_action_sync_context_lines,
        )
        if settings.v23_world_simulation_enabled:
            context = _attach_world_brief(user_id, world, time_ctx, context, settings)
        if trace is not None:
            trace.record(
                "world_context",
                (time.perf_counter() - started) * 1000,
                "ok",
                nearby=len(context.nearby_objects),
                salient=len(context.salient_events),
                recent_changes=len(context.recent_world_changes),
            )
        return context
    except Exception:
        logger.exception("世界上下文装配失败，本轮无世界段")
        if trace is not None:
            trace.record("world_context", 0.0, "error", error="world context failed")
        return None


def _attach_world_brief(user_id: str, world, time_ctx, context, settings):
    """V2.3.0 WorldBrief 装配（总闸内）；失败降级为无简报。"""
    try:
        from app.models.world_simulation import DailyPlanStatus
        from app.services.world import daily_plan as daily_plan_service
        from app.services.world import user_situation as situation_service
        from app.services.world import world_brief as brief_service

        block = None
        if settings.v23_daily_life_enabled:
            minutes = time_ctx.now.hour * 60 + time_ctx.now.minute
            plans = daily_plan_service.get_day_plan(
                user_id, time_ctx.now.date()
            )
            active = [p for p in plans if p.status == DailyPlanStatus.ACTIVE]
            block = active[0] if active else None
        situations = (
            situation_service.active_situations(user_id)
            if settings.v23_event_detection_enabled
            else []
        )
        brief = brief_service.build_world_brief(
            time_ctx,
            world,
            block,
            situations,
            context.salient_events,
            budget=settings.world_brief_char_budget,
        )
        return context.model_copy(update={"brief": brief})
    except Exception:
        logger.exception("世界简报装配失败，本轮无简报")
        return context


def _attach_world_impacts(user_id: str, facts: dict, now) -> dict:
    """V2.3.0 自治素材增强（v23 门控）：影响裁决包 + 当前日程块 + 活跃处境。"""
    try:
        settings = get_settings()
        if not settings.v23_world_simulation_enabled:
            return facts
        from app.models.world_simulation import DailyPlanStatus
        from app.services.world import daily_plan, event_impact, user_situation

        context: dict = {"part_of_day": facts.get("part_of_day")}
        if settings.v23_daily_life_enabled:
            minutes = now.hour * 60 + now.minute
            block = daily_plan.get_current_block(user_id, now.date(), minutes)
            context["current_block"] = (
                {
                    "activity": block.activity,
                    "part_of_day": block.part_of_day,
                    "location_id": block.location_id,
                }
                if block is not None
                else None
            )
        if settings.v23_event_detection_enabled:
            situations = user_situation.active_situations(user_id)
            context["active_situations"] = [
                {"dimension": s.dimension.value, "summary": s.summary, "intensity": s.intensity}
                for s in situations[:3]
            ]
            active_events = [
                event
                for event in world_repository.list_events(
                    world_repository.world_id_for(user_id),
                    statuses=["scheduled", "active"],
                    limit=10,
                )
            ]
            impacts = event_impact.evaluate_batch(active_events, context)[:3]
            if impacts:
                facts["impacts"] = [impact.to_dict() for impact in impacts]
            if context.get("current_block"):
                facts["current_block"] = context["current_block"]
            if context.get("active_situations"):
                facts["active_situations"] = context["active_situations"]
        return facts
    except Exception:
        logger.exception("世界影响素材装配失败，返回基础事实包")
        return facts


def collect_facts(user_id: str, provider: TimeProvider | None = None) -> dict:
    """自治只读事实包（autonomy-integration.md §1）：装配失败 → 空包。"""
    if not get_settings().world_enabled:
        return {}
    try:
        world = get_world(user_id)
        if world is None:
            return {}
        now = (provider or _default_provider).now(world)
        events = world_repository.list_events(
            world.world_id, statuses=["scheduled", "active"], limit=5
        )
        facts = {
            "part_of_day": part_of_day(now),
            "location": world.current_location,
            "weather": world.environment.weather,
            "salient_events": [
                event.brief(now)
                for event in events
                if event.status is EventStatus.ACTIVE
                or event.importance is EventImportance.HIGH
            ],
        }
        facts = _attach_world_impacts(user_id, facts, now)
        bounded, _ = bound_extra(facts, get_settings().observability_step_extra_max_chars)
        return bounded
    except Exception:
        logger.exception("世界事实装配失败，降级为空包")
        return {}


def run_maintenance(user_id: str | None = None) -> int:
    """世界维护单轮：到期触发 / 物品过期 / 宽限过期 / 保留清理。"""
    settings = get_settings()
    if not settings.world_enabled:
        return 0
    handled = 0
    worlds = (
        [get_world(user_id)]
        if user_id is not None
        else world_repository.list_all_worlds()
    )
    for world in worlds:
        if world is None:
            continue
        now = _default_provider.now(world)
        handled += trigger_due_events(world.user_id, now)
        handled += expire_due_objects(world.user_id, now)
        handled += expire_stale_events(world.user_id, now)
        try:
            cutoff = now - timedelta(days=settings.world_event_retention_days)
            handled += world_repository.prune_events_before(world.world_id, cutoff)
            handled += world_repository.prune_snapshots(
                world.world_id, settings.world_snapshot_max_per_world
            )
        except Exception:
            logger.exception("世界保留清理失败，下轮重试")
    return handled


async def run_world_maintenance_loop() -> None:
    """lifespan 常驻低频维护循环（H6）。"""

    await run_worker_loop(
        "world maintenance loop",
        run_maintenance,
        get_settings().world_maintenance_interval_seconds,
    )


_IMPORTANCE_ORDER = ("low", "normal", "high")


def _rank_drafts(drafts: list[dict]) -> list[dict]:
    """按重要度降序 + 幂等键升序排名：cap 边界取舍跨 tick 稳定。

    仅按重要度排序时会依赖输入顺序（不可控），同重要级事件在 cap 边界上
    可能跨 tick 摆动；幂等键是确定性派生，用作次级键可消除该抖动。
    """
    return sorted(
        drafts,
        key=lambda d: (
            -_IMPORTANCE_ORDER.index(d.get("importance", "low")),
            str(d.get("idempotency_key") or ""),
        ),
    )


def _digest_idempotency_key(user_id: str, drafts: list[dict]) -> str:
    """world_digest 幂等键：由被折叠内容的幂等键集合确定性派生。

    不用 datetime.now()：秒级时间戳在同一秒内多次 tick 会碰撞，且时钟回拨
    会产生重复摘要。派生键保证"同一批被折叠事件 → 同一摘要键"。
    """
    keys = sorted(str(d.get("idempotency_key") or "") for d in drafts)
    fingerprint = hashlib.sha1("|".join(keys).encode("utf-8")).hexdigest()[:16]
    return f"world_digest:{user_id}:{fingerprint}"


def _emit_simulation_events(user_id: str, drafts: list[dict]) -> list[str]:
    """模拟事件统一漏斗：单 tick 风暴上限，超出折叠为 world_digest。"""
    settings = get_settings()
    cap = settings.world_event_tick_cap
    if cap > 0 and len(drafts) > cap:
        ranked = _rank_drafts(drafts)
        kept, dropped = ranked[: cap - 1], ranked[cap - 1 :]
        digest = {
            "event_type": "world_digest",
            "title": f"世界变化摘要（{len(dropped)} 条）",
            "importance": "low",
            "source": "simulation",
            "status": "completed",
            "payload": {
                "count": len(dropped),
                "kinds": sorted({str(d.get("event_type", "")) for d in dropped}),
            },
            "idempotency_key": _digest_idempotency_key(user_id, dropped),
        }
        drafts = kept + [digest]
    emitted: list[str] = []
    for draft in drafts:
        event = create_event(user_id, **draft)
        if event is not None:
            emitted.append(draft["idempotency_key"])
    return emitted


def _run_simulation_substeps(user_id: str, now: datetime) -> None:
    """子步骤顺序不可调换：catch_up 必须先补齐断层，后续步骤才基于连续时间轴。

    catch_up（多日折叠）→ day_cycle（日/时段标记）→ weather → 处境过期
    → daily_life（计划构建/推进/历史裁剪）。
    """
    from app.services.world import catch_up, day_cycle, user_situation, weather

    catch_up.run_catch_up(user_id, now)
    marker_keys = day_cycle.emit_time_markers(user_id, now)
    weather.evolve_daily_weather(user_id)
    user_situation.expire_and_notify(user_id, now)
    settings = get_settings()
    if settings.v23_daily_life_enabled:
        from app.services.world import daily_plan

        world = get_world(user_id)
        if world is not None:
            world_now = _default_provider.now(world)
            plans = daily_plan.ensure_day_plan(user_id, world_now.date(), world_now)
            if plans:
                daily_plan.advance_daily_plan(user_id, world_now)
            else:
                logger.info("当日计划缺失且构建失败（user=%s）", user_id)
            if _day_rolled_over(marker_keys):
                daily_plan.prune_expired_plans(user_id, world_now.date())


def _day_rolled_over(marker_keys: list[str]) -> bool:
    """当日跨天标记触发时做一次日粒度维护（历史计划裁剪）。"""
    return any(key.startswith("time:day_start:") for key in marker_keys)


def run_simulation_maintenance(user_id: str | None = None, now: datetime | None = None):
    """V2.3.0 world_simulation 维护步：时间推进 + 日循环/天气/日程等子步骤。

    全程 0 LLM；异常按世界旁路纪律降级，不中断其它维护步。
    """
    settings = get_settings()
    if (
        not settings.world_enabled
        or not settings.v23_world_simulation_enabled
        or not settings.v23_time_advance_enabled
    ):
        return None
    worlds = (
        [ensure_world(user_id)]
        if user_id is not None
        else world_repository.list_all_worlds()
    )
    results = []
    for world in worlds:
        if world is None:
            continue
        step_now = now or datetime.now()
        result = advance_world_time(world.user_id, step_now)
        if result is not None:
            results.append(result)
        try:
            _run_simulation_substeps(world.user_id, step_now)
        except Exception:
            logger.exception("模拟子步骤执行失败：%s", world.user_id)
    return results


_V23_FLAG_NAMES = (
    "v23_world_simulation_enabled",
    "v23_time_advance_enabled",
    "v23_daily_life_enabled",
    "v23_event_detection_enabled",
    "v23_scene_expansion_enabled",
    "v23_habit_time_enabled",
    "v23_world_llm_assist_enabled",
    "v23_debug_tick_enabled",
)

_SIMULATION_EVENT_SOURCES = ("simulation",)
_SIMULATION_EVENT_TYPES = (
    "world_digest",
    "time_marker",
    "weather_change",
    "calendar_event",
    "life_event",
    "world_event",
)


def v23_flag_snapshot() -> dict:
    """调试面：7+1 个 v23 开关当前取值（只读）。"""
    settings = get_settings()
    return {name: bool(getattr(settings, name, False)) for name in _V23_FLAG_NAMES}


def build_debug_simulation(user_id: str) -> dict | None:
    """WS-018：模拟总览只读装配（复用 WS-012 brief 装配路径）。

    世界不存在 → None（端点转 404）；内部局部缺失降级为字段 null，不整体失败。
    """
    world = get_world(user_id)
    if world is None:
        return None
    settings = get_settings()
    time_ctx = _default_provider.context(world)
    block = None
    situations: list = []
    try:
        if settings.v23_daily_life_enabled:
            from app.models.world_simulation import DailyPlanStatus
            from app.services.world import daily_plan as daily_plan_service

            plans = daily_plan_service.get_day_plan(user_id, time_ctx.now.date())
            active = [p for p in plans if p.status == DailyPlanStatus.ACTIVE]
            block = active[0] if active else None
    except Exception:
        logger.exception("调试总览日程块装配失败")
    try:
        if settings.v23_event_detection_enabled:
            from app.services.world import user_situation as situation_service

            situations = situation_service.active_situations(user_id)
    except Exception:
        logger.exception("调试总览活跃处境装配失败")

    brief_text = ""
    world_section = None
    try:
        from app.services.world import world_brief as brief_service

        brief = brief_service.build_world_brief(
            time_ctx,
            world,
            block,
            situations,
            None,
            budget=settings.world_brief_char_budget,
        )
        brief_text = brief.text
        world_section = brief.model_dump(mode="json")
    except Exception:
        logger.exception("调试总览世界简报装配失败")

    recent_events: list[dict] = []
    try:
        events = world_repository.list_events(
            world.world_id, limit=40, order="created_at_desc"
        )
        for event in events:
            if event.type in _SIMULATION_EVENT_TYPES or event.source.value in _SIMULATION_EVENT_SOURCES:
                recent_events.append(
                    {
                        "id": event.id,
                        "type": event.type,
                        "title": event.title,
                        "importance": event.importance.value,
                        "status": event.status.value,
                        "idempotency_key": event.idempotency_key,
                        "created_at": event.created_at.isoformat() if event.created_at else None,
                    }
                )
            if len(recent_events) >= 10:
                break
    except Exception:
        logger.exception("调试总览近期模拟事件装配失败")

    return {
        "time_context": time_ctx.model_dump(mode="json"),
        "brief": {"text": brief_text, "parts": world_section},
        "current_block": block.brief() if block is not None else None,
        "active_situations": build_debug_situations(user_id),
        "recent_events": recent_events,
        "flags": v23_flag_snapshot(),
        "event_quota_drops": event_quota_drop_snapshot(),
    }


def build_debug_plan(user_id: str, day) -> list[dict]:
    """WS-018：当日计划只读装配；尚未生成 → 空列表（不落库）。"""
    from app.services.world import daily_plan as daily_plan_service

    plans = daily_plan_service.get_day_plan(user_id, day)
    blocks: list[dict] = []
    for plan in plans:
        item = plan.brief()
        item["variability_source"] = plan.variability_source.value
        item["note"] = plan.note
        blocks.append(item)
    return blocks


def build_debug_situations(user_id: str, include_expired: bool = False) -> list[dict]:
    """WS-018：处境只读装配；include_expired=True 时含 expired/dismissed。"""
    from app.repositories import world_simulation_repository
    from app.models.world_simulation import SituationStatus

    statuses = None if include_expired else (SituationStatus.ACTIVE,)
    situations = world_simulation_repository.list_situations(user_id, statuses=statuses)
    rows: list[dict] = []
    for situation in situations:
        rows.append(
            {
                "dimension": situation.dimension.value,
                "summary": situation.summary,
                "intensity": situation.intensity,
                "status": situation.status.value,
                "source": situation.source.value,
                "detected_at": (
                    situation.detected_at.isoformat() if situation.detected_at else None
                ),
                "valid_until": (
                    situation.valid_until.isoformat() if situation.valid_until else None
                ),
                "evidence": situation.evidence,
            }
        )
    return rows


def run_debug_tick(user_id: str) -> dict:
    """WS-018：手动执行一次模拟维护步（双闸保护；调用方负责门控）。"""
    results = run_simulation_maintenance(user_id) or []
    advanced_minutes = 0.0
    markers: list[str] = []
    for result in results:
        advanced_minutes += getattr(result, "advanced_minutes", 0.0)
        markers.append(getattr(result, "mode", "unknown"))

    plan_summary = None
    try:
        from app.services.world import daily_plan as daily_plan_service

        world = get_world(user_id)
        if world is not None and get_settings().v23_daily_life_enabled:
            now = _default_provider.now(world)
            plans = daily_plan_service.get_day_plan(user_id, now.date())
            plan_summary = {
                "date": now.date().isoformat(),
                "total": len(plans),
                "active": sum(1 for p in plans if p.status.value == "active"),
                "completed": sum(1 for p in plans if p.status.value == "completed"),
            }
    except Exception:
        logger.exception("调试 tick 计划摘要装配失败")

    return {
        "advanced_minutes": round(advanced_minutes, 2),
        "markers": markers,
        "plan_summary": plan_summary,
        "errors": [],
    }


def restore_snapshot(user_id: str, snapshot_id: str) -> World | None:
    """整包恢复（persistence.md §3）：Character 状态不回滚；恢复前自动留存快照。"""
    try:
        world = get_world(user_id)
        if world is None:
            return None
        target = world_repository.get_snapshot(world.world_id, snapshot_id)
        if target is None:
            return None
        pre = snapshot(user_id, label="pre_restore")
        if pre is None:
            return None
        state = target.state
        world.sim_time = (
            datetime.fromisoformat(state["sim_time"]) if state.get("sim_time") else None
        )
        world.current_location = state["current_location"]
        world.environment = WorldEnvironmentModel(**(state.get("environment") or {}))
        world.notes = []
        world_repository.save_world(world)
        world_repository.replace_entities(
            world.world_id,
            [WorldObject(**entity) for entity in state.get("entities", [])],
        )
        world_repository.replace_events(
            world.world_id,
            [WorldEvent(**event) for event in state.get("events", [])],
        )
        return get_world(user_id)
    except Exception:
        logger.exception("世界快照恢复失败")
        return None
