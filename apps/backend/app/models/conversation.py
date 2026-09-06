from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.character_state import CharacterState
from app.models.goal import GoalRecord
from app.models.memory import UserMemory
from app.models.reflection import InsightSummary
from app.models.relationship import RelationshipState


class ChatMessage(BaseModel):
    role: Literal["human", "ai"]
    content: str


class ConversationState(BaseModel):
    session_id: str
    user_id: str
    messages: list[ChatMessage]
    summary: str | None
    memories: list[UserMemory]
    current_input: str
    character_state: CharacterState = CharacterState()
    relationship_state: RelationshipState = RelationshipState()
    goals: list[GoalRecord] = []
    insights: list[InsightSummary] = []
    mode: str = "default"
    mode_entered_at: datetime | None = None
