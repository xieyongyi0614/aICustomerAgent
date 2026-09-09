"""V8 WorldEngine（architecture.md §2）：世界生命周期与装配编排。

只做调度与容错：世界读写经 world_repository，任何异常仅 log 并降级（None），
聊天与主动链路永不因世界而失败。
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from app.character.asuna.world import (
    DEFAULT_HOUSEHOLD,
    HOME_LOCATIONS,
    OBJECT_STATE_MACHINES,
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
    environment_lighting_suggestion,
    build_world_context,
)
from app.services.world.interpreter import interpret
from app.services.world.memory_bridge import materialize_event_memory

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
        if world is None or location_id not in HOME_LOCATIONS:
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


def seed_default_household(user_id: str) -> int:
    """幂等播种默认家庭库存；返回本次新建数量。已存在的同名物品不重复。"""
    try:
        world = ensure_world(user_id)
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
            and existing is None
            and settings.world_enabled
            and settings.world_household_autoseed_enabled
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
        world = ensure_world(user_id)
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
        if location_id not in HOME_LOCATIONS:
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


def create_event(
    user_id: str,
    event_type: str,
    title: str | None = None,
    importance: str = "normal",
    due_at: datetime | None = None,
    source: str = "manual",
) -> WorldEvent | None:
    try:
        world = ensure_world(user_id)
        if world is None:
            return None
        settings = get_settings()
        if (
            world_repository.count_active_events(world.world_id)
            >= settings.world_active_events_limit
        ):
            logger.warning("世界活跃事件数达上限，拒绝新建：%s", user_id)
            return None
        now = datetime.now()
        event = WorldEvent(
            id=world_repository.new_event_id(),
            world_id=world.world_id,
            type=event_type,
            title=title or event_type,
            importance=EventImportance(importance),
            status=EventStatus.SCHEDULED,
            due_at=due_at,
            payload={},
            source=EventSource(source),
            created_at=now,
            updated_at=now,
        )
        world_repository.save_event(event)
        return event
    except Exception:
        logger.exception("世界事件创建失败")
        return None


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
        if result.location_move is not None and set_location(user_id, result.location_move) is not None:
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
        context = build_world_context(
            world,
            entities,
            events,
            time_ctx,
            nearby_limit=settings.world_nearby_objects_limit,
            events_limit=settings.world_salient_events_limit,
        )
        if trace is not None:
            trace.record(
                "world_context",
                (time.perf_counter() - started) * 1000,
                "ok",
                nearby=len(context.nearby_objects),
                salient=len(context.salient_events),
            )
        return context
    except Exception:
        logger.exception("世界上下文装配失败，本轮无世界段")
        if trace is not None:
            trace.record("world_context", 0.0, "error", error="world context failed")
        return None


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
