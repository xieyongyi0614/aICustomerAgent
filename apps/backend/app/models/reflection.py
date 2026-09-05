"""Reflection 域模型（REF-001）。

Insight / ReflectionRun 服务层投影；状态与枚举是生命周期状态机的事实源。
类型终值由代码校准与复检决定（LLM 自报值仅作提案）。
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

InsightStatus = Literal["active", "superseded", "invalidated"]

InsightType = Literal["belief", "preference", "pattern"]

InsightScope = Literal["user", "relationship", "world"]

ReflectionRunStatus = Literal["queued", "running", "done", "skipped", "failed"]

ReflectionTrigger = Literal["scheduled", "event"]

INVALIDATION_SOURCE = Literal["user_clarification", "new_evidence", "judge"]


class InsightStatusEnum(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class InsightTypeEnum(StrEnum):
    BELIEF = "belief"
    PREFERENCE = "preference"
    PATTERN = "pattern"


class InsightScopeEnum(StrEnum):
    USER = "user"
    RELATIONSHIP = "relationship"
    WORLD = "world"


class ReflectionRunStatusEnum(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class ReflectionTriggerEnum(StrEnum):
    SCHEDULED = "scheduled"
    EVENT = "event"


class Insight(BaseModel):
    id: str
    user_id: str
    character_id: str = "asuna"
    statement: str
    type: InsightType
    confidence: float
    scope: InsightScope
    status: InsightStatus = "active"
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime
    invalidated_at: datetime | None = None
    invalidated_reason: str | None = None
    superseded_by: str | None = None


class ReflectionRun(BaseModel):
    id: str
    user_id: str
    character_id: str = "asuna"
    trigger: ReflectionTrigger
    status: ReflectionRunStatus
    evidence_summary: dict | None = None
    outcome: str | None = None
    llm_used: bool = False
    insight_ids: list[str] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
