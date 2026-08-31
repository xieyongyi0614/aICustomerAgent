from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.behavior import BehaviorDecision
from app.models.relationship import InteractionSignal, RelationshipEventDecision

UserEmotionLabel = Literal[
    "happy",
    "calm",
    "sad",
    "anxious",
    "angry",
    "tired",
    "excited",
    "neutral",
]

EventCategory = Literal[
    "achievement",
    "setback",
    "share_goal",
    "seek_help",
    "help_given",
    "complaint",
    "conflict",
    "daily",
    "farewell",
]


class UserEmotion(BaseModel):
    emotion: UserEmotionLabel = "neutral"
    event: EventCategory = "daily"


EmotionEventType = Literal[
    "praise",
    "comforted",
    "criticized",
    "teased",
    "conflict",
    "warm_moment",
    "funny_moment",
    "worrying_news",
    "reunion",
    "none",
]

EmotionMagnitude = Literal["weak", "normal", "strong"]


class EmotionEvent(BaseModel):
    type: EmotionEventType = "none"
    magnitude: EmotionMagnitude = "normal"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=50)


class TurnAnalysis(BaseModel):
    user_emotion: UserEmotion = UserEmotion()
    behavior: BehaviorDecision = BehaviorDecision()
    emotion_event: EmotionEvent = Field(default_factory=EmotionEvent)
    relationship_event: RelationshipEventDecision = Field(
        default_factory=RelationshipEventDecision
    )
    interaction_signal: InteractionSignal | None = None


class EmotionHistoryEntry(BaseModel):
    id: int
    user_id: str
    session_id: str
    user_emotion: str
    event: str
    behavior: str
    mood_before: str
    mood_after: str
    energy_after: float
    stage_after: str
    created_at: datetime
