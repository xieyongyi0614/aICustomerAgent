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
