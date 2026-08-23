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
