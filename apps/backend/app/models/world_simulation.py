"""V2.3.0 World Simulation 域模型（architecture.md §6）：DailyPlan / UserSituation。

纯数据定义，不绑定数据库、HTTP 与 LLM；状态机流转由服务层执行。
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

PARTS_OF_DAY = ("morning", "afternoon", "dusk", "evening", "late_night")


class DailyPlanStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    SUPERSEDED = "superseded"


class DailyPlanVariability(StrEnum):
    FIXED = "fixed"
    VARIANT = "variant"
    USER_INFLUENCED = "user_influenced"


class SituationDimension(StrEnum):
    HEALTH = "health"
    WORK_PRESSURE = "work_pressure"
    SCHEDULE_CHANGE = "schedule_change"
    TRAVEL = "travel"
    EMOTIONAL_CONTEXT = "emotional_context"


class SituationStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DISMISSED = "dismissed"


class SituationSource(StrEnum):
    CONVERSATION_PATTERN = "conversation_pattern"
    USER_DIRECTIVE = "user_directive"
    LLM_ASSIST = "llm_assist"


class DailyPlan(BaseModel):
    id: str
    user_id: str
    plan_date: date
    seq: int = Field(ge=0)
    part_of_day: str
    start_minutes: int = Field(ge=0, le=1439)
    end_minutes: int = Field(ge=0, le=1439)
    activity: str = Field(max_length=50)
    location_id: str = Field(max_length=50)
    variability_source: DailyPlanVariability = DailyPlanVariability.FIXED
    status: DailyPlanStatus = DailyPlanStatus.PLANNED
    routine_version: int = 1
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def brief(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "part_of_day": self.part_of_day,
            "start_minutes": self.start_minutes,
            "end_minutes": self.end_minutes,
            "activity": self.activity,
            "location_id": self.location_id,
            "status": self.status.value,
        }


class UserSituation(BaseModel):
    id: str
    user_id: str
    dimension: SituationDimension
    summary: str = Field(max_length=100)
    intensity: int = Field(ge=1, le=5)
    status: SituationStatus = SituationStatus.ACTIVE
    source: SituationSource = SituationSource.CONVERSATION_PATTERN
    evidence: dict[str, Any] = {}
    detected_at: datetime | None = None
    valid_until: datetime | None = None
    updated_at: datetime | None = None

    def brief(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "summary": self.summary,
            "intensity": self.intensity,
            "status": self.status.value,
        }


class SceneProfile(BaseModel):
    """场景画像（architecture.md §5.5）：地点对表达/话题/能量的刻画。"""

    location_id: str
    atmosphere_tags: list[str] = []
    tone_bias: str = "neutral"
    topic_affordances: list[str] = []
    expressiveness_cap: str = "rich"
    energy_bias: int = 0
    mood_bias: str | None = None


class WorldBrief(BaseModel):
    """世界简报（architecture.md §5.1）：世界"此刻状态"的 prompt 级聚合。"""

    text: str = ""
    time_line: str | None = None
    place_line: str | None = None
    situations_line: str | None = None
    events_line: str | None = None
