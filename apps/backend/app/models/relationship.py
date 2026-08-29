import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RelationshipStage = Literal["stranger", "friend", "close_friend", "partner"]

RelationshipEventType = Literal[
    "user_care",
    "user_help",
    "intimate_moment",
    "long_interaction",
    "praise",
    "criticized",
    "conflict",
    "boundary_violation",
    "none",
]


class RelationshipEventDecision(BaseModel):
    type: RelationshipEventType = "none"
    magnitude: Literal["weak", "normal", "strong"] = "normal"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=50)


class RelationshipState(BaseModel):
    intimacy: float = Field(default=0.3, ge=0.0, le=1.0)
    trust: float = Field(default=0.35, ge=0.0, le=1.0)
    familiarity: float = Field(default=0.3, ge=0.0, le=1.0)
    tension: float = Field(default=0.0, ge=0.0, le=1.0)
    stage: RelationshipStage = "friend"
    updated_at: datetime | None = None


class RelationshipDelta(BaseModel):
    intimacy: float = 0.0
    trust: float = 0.0
    familiarity: float = 0.0
    tension: float = 0.0


class RelationshipEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    character_id: str = "asuna"
    session_id: str
    type: RelationshipEventType
    magnitude: Literal["weak", "normal", "strong"]
    impact: RelationshipDelta
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["conversation", "memory_replay"] = "conversation"
    cause: str = Field(default="", max_length=50)
    created_at: datetime
