from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Mood = Literal[
    "happy",
    "calm",
    "worried",
    "sad",
    "shy",
    "excited",
    "tired",
    "angry",
]

EmotionLabel = Mood

EMOTION_CAUSE_MAX_LENGTH = 50


class CharacterEmotion(BaseModel):
    primary_emotion: EmotionLabel = "calm"
    intensity: float = Field(default=0.3, ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=EMOTION_CAUSE_MAX_LENGTH)
    updated_at: datetime | None = None


class CharacterState(BaseModel):
    mood: Mood = "calm"
    energy: float = Field(default=0.9, ge=0.0, le=1.0)
    current_topic: str = ""
    inner_state: str = "平静，期待和用户聊天"
    intensity: float = Field(default=0.3, ge=0.0, le=1.0)
    cause: str = Field(default="", max_length=EMOTION_CAUSE_MAX_LENGTH)
    last_event_at: datetime | None = None
    updated_at: datetime | None = None


class StateUpdateDecision(BaseModel):
    mood: Mood = "calm"
    mood_reason: str = ""
    inner_state: str = ""
    current_topic: str = ""
