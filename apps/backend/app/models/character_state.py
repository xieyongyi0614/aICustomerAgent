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


class CharacterState(BaseModel):
    mood: Mood = "calm"
    energy: float = Field(default=0.9, ge=0.0, le=1.0)
    current_topic: str = ""
    inner_state: str = "平静，期待和用户聊天"
    updated_at: datetime | None = None


class StateUpdateDecision(BaseModel):
    mood: Mood
    mood_reason: str = ""
    inner_state: str
    current_topic: str
