from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.behavior import BehaviorDecision

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


class TurnAnalysis(BaseModel):
    user_emotion: UserEmotion = UserEmotion()
    behavior: BehaviorDecision = BehaviorDecision()


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
