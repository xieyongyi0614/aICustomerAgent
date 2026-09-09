from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SceneIntent = Literal[
    "chat",
    "request_action",
    "continue_scene",
    "correct_scene",
    "interrupt",
    "question",
    "emotional",
]

SCENE_INTENT_EXAMPLES = (
    ("chat", "你好"),
    ("request_action", "给我拿瓶水"),
    ("continue_scene", "好的"),
    ("correct_scene", "你还没拿给我呢"),
    ("interrupt", "算了，不用了"),
    ("question", "你叫什么名字？"),
    ("emotional", "我有点累"),
)

ActionStatus = Literal["pending", "completed", "cancelled", "superseded"]

_SCENE_FIELD_MAX_LENGTH = 50


class SceneIntentResult(BaseModel):
    intent: SceneIntent
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class PendingAction(BaseModel):
    action: str = Field(max_length=_SCENE_FIELD_MAX_LENGTH)
    status: ActionStatus = "pending"
    created_at_turn: int = Field(default=0, ge=0)
    created_at: datetime | None = None


class SceneState(BaseModel):
    session_id: str
    turn_id: int = Field(default=0, ge=0)
    location: str | None = Field(default=None, max_length=_SCENE_FIELD_MAX_LENGTH)
    current_activity: str | None = Field(default=None, max_length=_SCENE_FIELD_MAX_LENGTH)
    current_action: str | None = Field(default=None, max_length=_SCENE_FIELD_MAX_LENGTH)
    pending_action: PendingAction | None = None
    scene_mood: str | None = Field(default=None, max_length=_SCENE_FIELD_MAX_LENGTH)
    last_active_at: datetime | None = None

    def persistent_dump(self) -> dict:
        return self.model_dump(exclude={"scene_mood"})


@dataclass
class SceneContext:
    state: SceneState
    intent: SceneIntent
    directive: str | None = None


class SceneActionDecision(BaseModel):
    location: str | None = Field(default=None, max_length=_SCENE_FIELD_MAX_LENGTH)
    current_activity: str | None = Field(default=None, max_length=_SCENE_FIELD_MAX_LENGTH)
    current_action: str | None = Field(default=None, max_length=_SCENE_FIELD_MAX_LENGTH)
    new_pending_action: str | None = Field(
        default=None, max_length=_SCENE_FIELD_MAX_LENGTH
    )
    pending_action_done: bool = False
    pending_action_cancel: bool = False
