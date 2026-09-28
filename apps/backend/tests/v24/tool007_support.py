"""TOOL-007 单测共享构造：世界事实夹具、设置替身与预读结果断言工具。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from app.application import world_engine
from app.models.world import WorldTimeMode
from app.models.world_simulation import (
    DailyPlan,
    DailyPlanStatus,
    SituationDimension,
    SituationSource,
    SituationStatus,
    UserSituation,
)
from app.repositories import world_repository, world_simulation_repository
from app.services.tool.context import ToolContext

NOW = datetime(2026, 9, 14, 12, 0, 0)
USER = "u-tool007"
LOCATION = "home.living_room"

DEFAULT_INVENTORY = ("苹果", "牛奶")
DEFAULT_SITUATIONS = (
    {"dimension": "health", "summary": "用户最近睡眠不足", "intensity": 3},
    {"dimension": "work_pressure", "summary": "用户项目临期", "intensity": 4},
    {"dimension": "emotional_context", "summary": "用户情绪偏低", "intensity": 2},
)


def world_settings(**overrides: Any) -> SimpleNamespace:
    """预读设置替身：世界可用、场景扩展默认关闭、工具总闸默认关。"""
    values: dict[str, Any] = {
        "world_time_mode": "real_sync",
        "world_sim_rate": 1.0,
        "scene_expansion_enabled": False,
        "tool_surface_max_tools": 12,
        "action_plan_expires_minutes": 5,
        "action_dedupe_window_hours": 24,
        "action_max_active_per_user": 5,
        "action_retry_max_attempts": 3,
        "action_retry_backoff_seconds": 1,
        "action_execution_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def tool_context(**overrides: Any) -> ToolContext:
    payload: dict[str, Any] = {
        "user_id": USER,
        "now": NOW,
        "settings": world_settings(),
        "run_kind": "foreground_chat",
    }
    payload.update(overrides)
    return ToolContext(**payload)


def seed_world(
    user_id: str = USER,
    *,
    location: str = LOCATION,
    weather: str = "sunny",
    time_mode: str = "real_sync",
) -> Any:
    """建世界记录（**不经 `ensure_world`**，避免自动播种污染库存夹具）。"""
    world = world_repository.ensure_world(user_id)
    world.time_mode = WorldTimeMode(time_mode)
    world.current_location = location
    world.environment.weather = weather
    world_repository.save_world(world)
    return world


def seed_object(user_id: str = USER, name: str = "苹果", location: str = LOCATION) -> Any:
    obj = world_engine.create_object(user_id, name=name, location_id=location)
    assert obj is not None
    return obj


def seed_objects(user_id: str = USER, names: tuple[str, ...] = DEFAULT_INVENTORY) -> None:
    for name in names:
        seed_object(user_id, name)


def seed_event(
    user_id: str = USER,
    *,
    title: str = "复查",
    importance: str = "normal",
    due_in_hours: int = 2,
    event_type: str = "reminder",
    status: str = "scheduled",
) -> Any:
    event = world_engine.create_event(
        user_id,
        event_type,
        title,
        importance,
        NOW + timedelta(hours=due_in_hours),
        "user_mention",
        status=status,
    )
    assert event is not None
    return event


def seed_plan(
    user_id: str = USER,
    *,
    activity: str = "看书",
    location: str = LOCATION,
    part_of_day: str = "afternoon",
    start_minutes: int = 600,
    end_minutes: int = 900,
    status: str = DailyPlanStatus.ACTIVE,
    plan_date: Any = None,
) -> Any:
    day = plan_date or NOW.date()
    plan = DailyPlan(
        id=f"plan-{user_id}-{activity}",
        user_id=user_id,
        plan_date=day,
        seq=1,
        part_of_day=part_of_day,
        start_minutes=start_minutes,
        end_minutes=end_minutes,
        activity=activity,
        location_id=location,
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )
    world_simulation_repository.save_plan(plan)
    return plan


def seed_situation(
    user_id: str = USER,
    *,
    dimension: str = "health",
    summary: str = "用户最近睡眠不足",
    intensity: int = 3,
    status: str = SituationStatus.ACTIVE,
) -> Any:
    situation = UserSituation(
        id=f"sit-{user_id}-{dimension}",
        user_id=user_id,
        dimension=SituationDimension(dimension),
        summary=summary,
        intensity=intensity,
        status=SituationStatus(status),
        source=SituationSource.CONVERSATION_PATTERN,
        detected_at=NOW,
        updated_at=NOW,
    )
    world_simulation_repository.save_situation(situation)
    return situation


def seed_all(user_id: str = USER, **overrides: Any) -> Any:
    """标准世界夹具：世界 + 两件物品 + 一条日程块 + 一条处境 + 一条事件。"""
    world = seed_world(
        user_id,
        location=overrides.get("location", LOCATION),
        weather=overrides.get("weather", "sunny"),
        time_mode=overrides.get("time_mode", "real_sync"),
    )
    seed_objects(user_id, overrides.get("inventory", DEFAULT_INVENTORY))
    if overrides.get("with_plan", True):
        seed_plan(user_id, **overrides.get("plan_kwargs", {}))
    if overrides.get("with_situation", True):
        seed_situation(user_id)
    if overrides.get("with_event", True):
        seed_event(user_id)
    return world


def world_segment_keys() -> tuple[str, ...]:
    from app.services.tool.world_context import WORLD_SEGMENT_KEYS

    return WORLD_SEGMENT_KEYS


def facts_keys() -> tuple[str, ...]:
    from app.services.tool.world_context import WORLD_FACTS_KEYS

    return WORLD_FACTS_KEYS


def world_objects(user_id: str = USER) -> list[str]:
    world = world_repository.get_world(user_id)
    if world is None:
        return []
    return [obj.name for obj in world_repository.list_objects(world.world_id, status="active")]


def world_event_titles(user_id: str = USER) -> list[str]:
    world = world_repository.get_world(user_id)
    if world is None:
        return []
    return [event.title for event in world_repository.list_events(world.world_id, limit=50)]


def object_location(user_id: str, name: str) -> str | None:
    obj = world_engine.find_object_by_name(user_id, name)
    return None if obj is None else obj.location_id
