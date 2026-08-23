from typing import Literal

from pydantic import BaseModel

from app.models.character_state import CharacterState
from app.models.memory import UserMemory
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
