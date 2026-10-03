from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field
from app.core import ids

RelationshipStage = Literal["stranger", "friend", "close_friend", "partner"]

RelationshipEventType = Literal[
    "user_care",
    "user_help",
    "intimate_moment",
    "long_interaction",
    "praise",
    "warm_moment",
    "criticized",
    "conflict",
    "boundary_violation",
    "promise_kept",
    "promise_broken",
    "none",
]

RelationshipEventSource = Literal["conversation", "memory_replay", "system"]

InteractionKind = Literal[
    "smalltalk",
    "self_disclosure",
    "support",
    "request_help",
    "gratitude",
    "humor",
    "promise",
    "teaching",
    "shared_activity",
    "appreciation",
    "criticism",
    "boundary_violation",
    "conflict",
    "ambient",
]

SignalQuality = Literal["positive", "neutral", "negative"]

ConflictStatus = Literal["none", "strain", "conflict", "cold", "recovery", "resolved"]

ConflictResolution = Literal["reconciled", "time_heals", ""]


class RelationshipEventDecision(BaseModel):
    type: RelationshipEventType = "none"
    magnitude: Literal["weak", "normal", "strong"] = "normal"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=50)


class InteractionSignal(BaseModel):
    kind: InteractionKind
    quality: SignalQuality = "neutral"
    salience: float = Field(default=0.0, ge=0.0, le=1.0)
    novelty: float = Field(default=1.0, ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=50)


class RelationshipState(BaseModel):
    intimacy: float = Field(default=0.3, ge=0.0, le=1.0)
    trust: float = Field(default=0.35, ge=0.0, le=1.0)
    familiarity: float = Field(default=0.3, ge=0.0, le=1.0)
    respect: float = Field(default=0.6, ge=0.0, le=1.0)
    comfort: float = Field(default=0.6, ge=0.0, le=1.0)
    tension: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: RelationshipStage = "friend"
    conflict_status: ConflictStatus = "none"
    neglect_active: bool = False
    last_interaction_at: datetime | None = None
    version: int = Field(default=0, ge=0)
    updated_at: datetime | None = None


class RelationshipDelta(BaseModel):
    intimacy: float = 0.0
    trust: float = 0.0
    familiarity: float = 0.0
    respect: float = 0.0
    comfort: float = 0.0
    tension: float = 0.0


class RelationshipEvent(BaseModel):
    id: str = Field(default_factory=ids.new_id_str)
    user_id: str
    character_id: str = "asuna"
    session_id: str
    type: RelationshipEventType
    magnitude: Literal["weak", "normal", "strong"]
    impact: RelationshipDelta
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: RelationshipEventSource = "conversation"
    cause: str = Field(default="", max_length=50)
    created_at: datetime


@dataclass(frozen=True)
class MilestoneSpec:
    key: str
    title: str
    detect: Callable[[Any], bool]
    bonus: RelationshipDelta = field(default_factory=RelationshipDelta)
    memory_worthy: bool = False
    unlocks: tuple[str, ...] = ()


class MilestoneRecord(BaseModel):
    id: str = Field(default_factory=ids.new_id_str)
    user_id: str
    character_id: str = "asuna"
    milestone_key: str
    period_key: str = ""
    title: str = ""
    applied_bonus: RelationshipDelta = Field(default_factory=RelationshipDelta)
    unlocks: tuple[str, ...] = ()
    meta: dict = Field(default_factory=dict)
    created_at: datetime


class ConflictRecord(BaseModel):
    id: str = Field(default_factory=ids.new_id_str)
    user_id: str
    character_id: str = "asuna"
    status: ConflictStatus
    trigger_event_id: str | None = None
    started_at: datetime
    last_negative_at: datetime | None = None
    recovery_started_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: ConflictResolution = ""
    created_at: datetime


class RelationshipSnapshot(BaseModel):
    id: str = Field(default_factory=ids.new_id_str)
    user_id: str
    character_id: str = "asuna"
    version: int = 0
    dimensions: dict[str, float] = Field(default_factory=dict)
    stage: RelationshipStage = "friend"
    conflict_status: ConflictStatus = "none"
    trigger: str = "manual"
    created_at: datetime


SharedExperienceKind = Literal[
    "relationship_event", "relationship_fact", "experience", "world_event"
]


class SharedExperience(BaseModel):
    """共同经历投影条目（REL-002，只读可重算；source_ref 可回指唯一源行）。"""

    entry_id: str
    kind: SharedExperienceKind
    title: str
    occurred_at: datetime
    source_ref: dict = Field(default_factory=dict)
    ledger_event_id: str | None = None
    salience: float = 0.0
