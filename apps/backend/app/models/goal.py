import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

GoalType = Literal["user_care", "relationship", "conversation", "scene"]

GoalStatus = Literal["active", "completed", "expired", "cancelled"]

GoalSource = Literal["definition", "policy", "scene"]

GoalHorizon = Literal["persistent", "current"]

GOAL_TIER: dict[str, int] = {
    "scene": 0,
    "user_care": 1,
    "relationship": 2,
    "conversation": 3,
}

GOAL_DESCRIPTION_MAX_LENGTH = 40
GOAL_PRIORITY_MIN = 1
GOAL_PRIORITY_MAX = 5


class GoalSeed(BaseModel):
    type: GoalType
    description: str = Field(max_length=GOAL_DESCRIPTION_MAX_LENGTH)
    priority: int = Field(ge=GOAL_PRIORITY_MIN, le=GOAL_PRIORITY_MAX)


class GoalRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    character_id: str = "asuna"
    type: GoalType
    description: str = Field(max_length=GOAL_DESCRIPTION_MAX_LENGTH)
    priority: int = Field(ge=GOAL_PRIORITY_MIN, le=GOAL_PRIORITY_MAX, default=3)
    status: GoalStatus = "active"
    horizon: GoalHorizon = "current"
    source: GoalSource = "policy"
    created_turn: int = 0
    expires_at_turn: int | None = None
    created_at: datetime
    updated_at: datetime
