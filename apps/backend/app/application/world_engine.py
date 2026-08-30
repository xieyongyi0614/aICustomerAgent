"""V8 WorldEngine（architecture.md §2）：世界生命周期与装配编排。

只做调度与容错：世界读写经 world_repository，任何异常仅 log 并降级（None），
聊天与主动链路永不因世界而失败。
"""

import logging
from datetime import datetime

from app.character.asuna.world import HOME_LOCATIONS, OBJECT_STATE_MACHINES
from app.core.settings import get_settings
from app.models.world import (
    ObjectStatus,
    StateSnapshot,
    World,
    WorldObject,
    WorldTimeMode,
    apply_object_action as apply_machine_action,
    object_default_portions,
    object_initial_state,
)
from app.repositories import world_repository
from app.services.world.locations import build_location_context
from app.services.world.time_provider import TimeProvider

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
        return world_repository.ensure_world(user_id)
    except Exception:
        logger.exception("世界初始化失败，降级为无世界")
        return None


def get_world(user_id: str) -> World | None:
    try:
        return world_repository.get_world(user_id)
    except Exception:
        logger.exception("世界读取失败，降级为无世界")
        return None


def create_object(
    user_id: str,
    name: str,
    category: str = "misc",
    location_id: str | None = None,
    quantity: float = 1.0,
    aliases: list[str] | None = None,
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
