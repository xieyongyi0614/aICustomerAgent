"""V8 World 域模型（world-model.md §2 / object-system.md §3 / time-system.md §2）。

纯数据定义与纯函数：WorldObject / WorldEvent / TimeContext / WorldContext 等；
不绑定数据库、HTTP 与 LLM。世界状态机为纯函数 apply_object_action。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.core import timeutil
from app.models.observability import bound_extra, bound_text
from app.models.world_simulation import WorldBrief

WORLD_DB_CATEGORIES = ("food", "drink", "tool", "furniture", "clothing", "device", "misc")


class WorldTimeMode(StrEnum):
    REAL_SYNC = "real_sync"
    SIMULATED = "simulated"
    STORY = "story"


class ObjectStatus(StrEnum):
    ACTIVE = "active"
    DESTROYED = "destroyed"


class ConsumeError(StrEnum):
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    NOT_CONSUMABLE = "NOT_CONSUMABLE"
    INSUFFICIENT_QUANTITY = "INSUFFICIENT_QUANTITY"
    INVALID_QUANTITY = "INVALID_QUANTITY"


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class EventImportance(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class EventSource(StrEnum):
    USER_MENTION = "user_mention"
    MANUAL = "manual"
    AUTONOMY = "autonomy"
    CHARACTER = "character"
    TIME = "time"
    WEATHER = "weather"
    CALENDAR = "calendar"
    USER_EVIDENCE = "user_evidence"
    DAILY_LIFE = "daily_life"
    SIMULATION = "simulation"


PART_OF_DAY_CN = {
    "morning": "上午",
    "afternoon": "中午",
    "dusk": "下午",
    "evening": "晚上",
    "late_night": "深夜",
}

WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def part_of_day(now: datetime) -> str:
    if 5 <= timeutil.local(now).hour < 11:
        return "morning"
    if 11 <= timeutil.local(now).hour < 14:
        return "afternoon"
    if 14 <= timeutil.local(now).hour < 18:
        return "dusk"
    if 18 <= timeutil.local(now).hour < 23:
        return "evening"
    return "late_night"


def apply_object_action(machine: dict, category: str, state: str, action: str) -> str | None:
    """按类目状态机返回迁移后的状态；非法/未知动作返回 None（宁缺毋滥，不造事实）。"""
    spec = machine.get(category) or machine.get("generic")
    if spec is None:
        return None
    rule = (spec.get("transitions") or {}).get(action)
    if rule is None:
        return None
    from_states = rule.get("from") or []
    if "*" not in from_states and state not in from_states:
        return None
    return rule["to"]


def object_initial_state(machine: dict, category: str) -> str:
    spec = machine.get(category) or machine.get("generic")
    return spec["initial"] if spec else "intact"


def object_default_portions(machine: dict, category: str) -> int:
    spec = machine.get(category) or machine.get("generic")
    return int(spec.get("default_portions", 1)) if spec else 1


class WorldObject(BaseModel):
    id: str
    world_id: str
    name: str
    aliases: list[str] = []
    category: str = "misc"
    location_id: str
    state: str
    quantity: float = Field(default=1.0, ge=0.0)
    unit: str = ""
    consumable: bool = False
    properties: dict[str, Any] = {}
    status: ObjectStatus = ObjectStatus.ACTIVE
    last_action_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def brief(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "location_id": self.location_id,
            "state": self.state,
            "quantity": self.quantity,
        }


class WorldEnvironment(BaseModel):
    weather: str | None = None
    temperature_c: float | None = None
    lighting: str | None = None
    noise: str | None = None
    atmosphere: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None


class World(BaseModel):
    """世界聚合根读模型（world-model.md §2）。"""

    world_id: str
    user_id: str
    name: str = "家"
    time_mode: WorldTimeMode = WorldTimeMode.REAL_SYNC
    sim_time: datetime | None = None
    sim_last_advanced_at: datetime | None = None
    sim_rate: float = 1.0
    current_location: str = "home.living_room"
    environment: WorldEnvironment = Field(default_factory=WorldEnvironment)
    notes: list[str] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WorldEvent(BaseModel):
    id: str
    world_id: str
    type: str
    title: str
    importance: EventImportance = EventImportance.NORMAL
    status: EventStatus = EventStatus.SCHEDULED
    started_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    payload: dict[str, Any] = {}
    source: EventSource = EventSource.USER_MENTION
    idempotency_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def brief(self, now: datetime) -> dict[str, Any]:
        due_in_hours = None
        if self.due_at is not None and self.status == EventStatus.SCHEDULED:
            due_in_hours = round((self.due_at - now).total_seconds() / 3600, 1)
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "importance": self.importance.value,
            "status": self.status.value,
            "due_in_hours": due_in_hours,
        }


class TimeContext(BaseModel):
    now: datetime
    weekday: str
    part_of_day: str
    time_mode: WorldTimeMode
    note: str | None = None

    def day_line(self) -> str:
        clock = self.now.strftime("%H:%M")
        return f"现在是{self.weekday}{PART_OF_DAY_CN.get(self.part_of_day, '')} {clock}"


class LocationContext(BaseModel):
    current: str
    current_name: str
    path: list[str] = []
    available_actions: list[str] = []
    traits: list[str] = []


class ObjectBrief(BaseModel):
    name: str
    state: str
    quantity: float
    location_name: str | None = None


class InventoryItem(BaseModel):
    """WorldContext 中的家庭库存条目：位置 + 数量 + 单位 + consumable 事实。"""

    name: str
    quantity: float
    unit: str = ""
    location_id: str
    location_name: str | None = None
    state: str
    consumable: bool = False


class ConsumeResult(BaseModel):
    """统一 Consume 的结构化结果（错误由代码表达，不依赖 LLM 判断）。"""

    ok: bool
    error: ConsumeError | None = None
    object: WorldObject | None = None
    previous_quantity: float | None = None


class EventBrief(BaseModel):
    id: str
    type: str
    title: str
    importance: str
    status: str
    due_in_hours: float | None = None


class WorldContext(BaseModel):
    time: TimeContext
    location: LocationContext
    environment: WorldEnvironment | None = None
    nearby_objects: list[ObjectBrief] = []
    inventory: list[InventoryItem] = []
    salient_events: list[EventBrief] = []
    recent_world_changes: list[str] = []
    notes: list[str] = []
    brief: WorldBrief | None = None


class WorldFacts(BaseModel):
    """自治只读事实包（autonomy-integration.md §1）。"""

    weather: str | None = None
    part_of_day: str | None = None
    location: str | None = None
    salient_events: list[EventBrief] = []


class StateSnapshot(BaseModel):
    id: str
    world_id: str
    label: str | None = None
    state: dict[str, Any]
    created_at: datetime | None = None


def bounded_notes(notes: list[str], max_chars: int) -> list[str]:
    bounded: list[str] = []
    total = 0
    for note in notes:
        text, _ = bound_text(note, max(32, max_chars // 4))
        if total + len(text) > max_chars:
            break
        bounded.append(text)
        total += len(text)
    return bounded
