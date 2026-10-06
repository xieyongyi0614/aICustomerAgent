"""V2.4.0 TOOL-007 世界事实预读装配（architecture.md §7.3、TOOL-007 §2.2、§2.3、§4.1）。

只读契约的读半边：调用方（`action_engine._build_snapshot`）在闸门之外预读世界事实，
注入 `ToolContext`；工具实现体零仓储读取（`tests/v24/test_tool_world_guard.py` 静态强制）。

八段预读（每段独立 try，失败只缺省该段并记日志，**绝不抛出**）：

```text
① 世界基本信息（worlds.current_location / environment.weather）  world_engine.get_world
② 日时段（TimeContext.part_of_day）                              services.world.time_provider
③ 当前日程块（daily_plans active / 时间窗命中）                    services.world.daily_plan
④ 活跃事件（scheduled/active，≤5，重要性 → due_at 确定性排序）      world_engine.list_active_events
⑤ 库存（活跃物品名，≤20）                                         world_engine.list_active_objects
⑥ 活跃处境（≤3）                                                 services.world.user_situation
⑦ 场景画像（SceneProfile）                                       character.asuna.scene_profiles
⑧ 关系阶段投影（{stage, tension}）                                services.state_service
```

**纯读纪律**：只调 `world_engine` / `services/world/*` 的只读函数（`get_` / `list_` / `build_`）；
**不得隐式 `ensure_world`**（E2：缺世界记录时缺省返回，不创建世界、不落库）；
`world_engine.build_time_context` / `get_location_context` 内部会 `ensure_world`，故本模块自行经
`TimeProvider.context(world)` 取日时段，不走它们。

**键集**（`build()[ToolContext 字段名]`，§2.2）：

| 键 | 值 |
|---|---|
| `world` | `{world_enabled, location, location_name, weather, part_of_day, current_block, active_events, locations}` |
| `inventory` / `situations` / `scene` / `relationship` | 逐段值（失败或缺省为 `[]` / `{}`） |

`world["locations"]` 是 TOOL-004 `ToolContext.world_locations()` 定义、TOOL-003 `location_exists`
消费的**已知地点词表**（注册表 id ∪ 中文名），本任务供数据（§5 Step 3）。
`world_enabled` 恒存在 = **已装配标记**：本装配器恒产出装配态；「未装配」表现为
`world` 段整体缺席，消费方据此保守降级。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Any

from app.core import timeutil
from app.services.world import engine_port as world_engine
from app.character.asuna.scene_profiles import scene_profile_for
from app.character.asuna.world import WORLD_LOCATION_REGISTRY
from app.services.conversation.state import load_relationship
from app.services.tool.context import WORLD_ENABLED_KEY, ToolContext
from app.services.world import daily_plan, user_situation
from app.services.world.locations import location_name
from app.services.world.time_provider import TimeProvider

logger = logging.getLogger(__name__)

WORLD_FACTS_KEYS: tuple[str, ...] = (
    "world",
    "inventory",
    "situations",
    "scene",
    "relationship",
)
"""`build()` 返回值键集 = `ToolContext` 世界域字段名（顺序即装配顺序）。"""

WORLD_SEGMENT_KEYS: tuple[str, ...] = (
    WORLD_ENABLED_KEY,
    "location",
    "location_name",
    "weather",
    "part_of_day",
    "current_block",
    "active_events",
    "locations",
)
"""`world` 段键集（§2.2 世界事实段 + 地点词表读面）。"""

INVENTORY_LIMIT = 20
SITUATIONS_LIMIT = 3
ACTIVE_EVENTS_LIMIT = 5

SEGMENT_WORLD = "world"
SEGMENT_PART_OF_DAY = "part_of_day"
SEGMENT_CURRENT_BLOCK = "current_block"
SEGMENT_ACTIVE_EVENTS = "active_events"
SEGMENT_INVENTORY = "inventory"
SEGMENT_SITUATIONS = "situations"
SEGMENT_SCENE = "scene"
SEGMENT_RELATIONSHIP = "relationship"

_IMPORTANCE_RANK: dict[str, int] = {"high": 0, "normal": 1, "low": 2}


def _degrade(segment: str, user_id: str, exc: Exception) -> None:
    """逐段降级日志：该段缺省，其余段与整体不受影响（世界旁路纪律）。"""
    logger.warning(
        "世界事实预读段降级（%s，user=%s）：%s", segment, user_id, exc, exc_info=True
    )


def known_locations() -> tuple[str, ...]:
    """已知地点词表：注册表 id ∪ 中文名（确定性排序，纯资产读取）。"""
    ids = {str(location_id) for location_id in WORLD_LOCATION_REGISTRY}
    names = {
        str(definition["name"])
        for definition in WORLD_LOCATION_REGISTRY.values()
        if definition.get("name")
    }
    return tuple(sorted(ids | names))


def _block_dict(block: Any) -> dict[str, Any] | None:
    if block is None:
        return None
    return {
        "activity": block.activity,
        "location_id": block.location_id,
        "part_of_day": block.part_of_day,
    }


def _event_dict(event: Any) -> dict[str, Any]:
    due_at = getattr(event, "due_at", None)
    return {
        "type": str(getattr(event, "type", "")),
        "title": str(getattr(event, "title", "")),
        "due_at": due_at.isoformat() if isinstance(due_at, datetime) else None,
    }


def _event_order_key(event: Any) -> tuple[int, float, str]:
    """确定性排序键：重要性（high → low）→ due_at（无到期时间排后）→ 事件 id。"""
    importance = getattr(getattr(event, "importance", None), "value", None)
    due_at = getattr(event, "due_at", None)
    due_key = due_at.timestamp() if isinstance(due_at, datetime) else float("inf")
    return (
        _IMPORTANCE_RANK.get(str(importance), len(_IMPORTANCE_RANK)),
        due_key,
        str(getattr(event, "id", "")),
    )


class WorldContextBuilder:
    """世界事实预读装配器（TOOL-007 §4.1）：无共享可变状态，并发安全（E15）。

    `settings` 可在构造或 `build()` 传入（后者优先），经 `build_scene` 透传。
    """

    def __init__(self, settings: Any = None) -> None:
        self._settings = settings

    def build(
        self, user_id: str, *, now: datetime, settings: Any = None
    ) -> dict[str, Any]:
        """八段预读；返回 `ToolContext` 世界域字段集合（§2.2 键集，失败逐段降级）。"""
        resolved = settings if settings is not None else self._settings
        world = self._read_world(user_id)
        return {
            "world": self._world_segment(user_id, world, now),
            "inventory": self.build_inventory(user_id),
            "situations": self.build_situations(user_id),
            "scene": self.build_scene(user_id, world=world, settings=resolved),
            "relationship": self.build_relationship(user_id),
        }

    def build_inventory(self, user_id: str, limit: int = INVENTORY_LIMIT) -> list[str]:
        """⑤ 库存：活跃物品名（≤ limit 件）。失败 → `[]`（语义校验器降级放行）。"""
        try:
            return [str(obj.name) for obj in world_engine.list_active_objects(user_id)[:limit]]
        except Exception as exc:
            _degrade(SEGMENT_INVENTORY, user_id, exc)
            return []

    def build_situations(
        self, user_id: str, limit: int = SITUATIONS_LIMIT
    ) -> list[dict[str, Any]]:
        """⑥ 活跃处境（≤ limit 条）；失败 → `[]`。"""
        try:
            situations = user_situation.active_situations(user_id)[:limit]
            return [
                {
                    "dimension": str(situation.dimension.value),
                    "summary": situation.summary,
                    "intensity": situation.intensity,
                }
                for situation in situations
            ]
        except Exception as exc:
            _degrade(SEGMENT_SITUATIONS, user_id, exc)
            return []

    def build_scene(
        self, user_id: str, *, world: Any = None, settings: Any = None
    ) -> dict[str, Any]:
        """⑦ 场景画像 `{location_id, tone_bias, topic_affordances}`。"""
        resolved = settings if settings is not None else self._settings
        try:
            current = world if world is not None else world_engine.get_world(user_id)
            if current is None:
                return {}
            profile = scene_profile_for(str(current.current_location))
            return {
                "location_id": profile.location_id,
                "tone_bias": profile.tone_bias,
                "topic_affordances": list(profile.topic_affordances),
            }
        except Exception as exc:
            _degrade(SEGMENT_SCENE, user_id, exc)
            return {}

    def build_relationship(self, user_id: str) -> dict[str, Any]:
        """⑧ 关系阶段投影 `{stage, tension}`（只读）；失败 → `{}`（关系维度不裁剪，E11）。"""
        try:
            relationship = load_relationship(user_id)
            return {
                "stage": str(relationship.stage),
                "tension": float(relationship.tension),
            }
        except Exception as exc:
            _degrade(SEGMENT_RELATIONSHIP, user_id, exc)
            return {}

    def _read_world(self, user_id: str) -> Any:
        """① 世界基本信息；无世界记录返回 None（**不 ensure_world**，E2）。失败 → None。"""
        try:
            return world_engine.get_world(user_id)
        except Exception as exc:
            _degrade(SEGMENT_WORLD, user_id, exc)
            return None

    def _world_segment(self, user_id: str, world: Any, now: datetime) -> dict[str, Any]:
        """①~④ + 地点词表 → `world` 段（逐段降级，键恒齐全）。"""
        segment: dict[str, Any] = {WORLD_ENABLED_KEY: True}
        segment["location"], segment["location_name"], segment["weather"] = self._place(user_id, world)
        time_ctx = self._time_context(user_id, world, now)
        segment["part_of_day"] = None if time_ctx is None else str(time_ctx.part_of_day)
        segment["current_block"] = self._current_block(user_id, time_ctx, now)
        segment["active_events"] = self._active_events(user_id)
        segment["locations"] = self._locations()
        return segment

    def _place(self, user_id: str, world: Any) -> tuple[str | None, str | None, str | None]:
        """① 地点 id / 中文名（未注册回退原始 id，E5）/ 天气。"""
        if world is None:
            return None, None, None
        try:
            location = str(world.current_location)
            return location, location_name(location) or location, world.environment.weather
        except Exception as exc:
            _degrade(SEGMENT_WORLD, user_id, exc)
            return None, None, None

    def _time_context(self, user_id: str, world: Any, now: datetime) -> Any:
        """② 日时段：世界时钟优先（simulated/story），real_sync 取调用方时刻。"""
        if world is None:
            return None
        try:
            return TimeProvider(real_now=lambda: now).context(world)
        except Exception as exc:
            _degrade(SEGMENT_PART_OF_DAY, user_id, exc)
            return None

    def _current_block(self, user_id: str, time_ctx: Any, now: datetime) -> dict[str, Any] | None:
        """③ 当前日程块：active 优先，其次时间窗命中的 planned；无块或缺省 → None（E3）。"""
        moment = getattr(time_ctx, "now", None) or now
        try:
            block = daily_plan.get_current_block(
                user_id, timeutil.local(moment).date(), timeutil.local(moment).hour * 60 + moment.minute
            )
            return _block_dict(block)
        except Exception as exc:
            _degrade(SEGMENT_CURRENT_BLOCK, user_id, exc)
            return None

    def _active_events(self, user_id: str) -> list[dict[str, Any]]:
        """④ 活跃事件：重要性 → due_at → id 确定性排序后截断至 5 条（E6）。"""
        try:
            events = sorted(
                world_engine.list_active_events(user_id), key=_event_order_key
            )
            return [_event_dict(event) for event in events[:ACTIVE_EVENTS_LIMIT]]
        except Exception as exc:
            _degrade(SEGMENT_ACTIVE_EVENTS, user_id, exc)
            return []

    def _locations(self) -> tuple[str, ...]:
        try:
            return known_locations()
        except Exception as exc:
            logger.warning("世界事实预读段降级（locations）：%s", exc, exc_info=True)
            return ()


def apply_world_facts(ctx: ToolContext, facts: dict[str, Any]) -> ToolContext:
    """按 `WORLD_FACTS_KEYS` 覆写 `ToolContext` 世界域字段（不改原快照）。"""
    updates = {key: facts[key] for key in WORLD_FACTS_KEYS if key in facts}
    return replace(ctx, **updates) if updates else ctx


def build_tool_context(
    ctx: ToolContext, *, settings: Any = None, now: datetime | None = None
) -> ToolContext:
    """总闸已开的调用方入口：预读八段并注入 `ToolContext`（失败逐段降级，不抛出）。"""
    resolved_settings = settings if settings is not None else ctx.settings
    moment = now if now is not None else (timeutil.ensure_aware(ctx.now) or timeutil.now())
    facts = WorldContextBuilder(resolved_settings).build(
        ctx.user_id, now=moment, settings=resolved_settings
    )
    return apply_world_facts(ctx, facts)
