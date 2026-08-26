from datetime import datetime

from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str | None = None
    content: str


class ChatSessionResponse(BaseModel):
    session_id: str


class ChatDelta(BaseModel):
    delta: str


class ChatDone(BaseModel):
    done: bool = True


class CharacterStateOut(BaseModel):
    mood: str
    energy: float
    current_topic: str
    inner_state: str
    updated_at: datetime | None = None


class RelationshipStateOut(BaseModel):
    intimacy: float
    trust: float
    familiarity: float
    stage: str
    updated_at: datetime | None = None


class EmotionHistoryItem(BaseModel):
    user_emotion: str
    event: str
    behavior: str
    mood_before: str
    mood_after: str
    energy_after: float
    stage_after: str
    created_at: datetime


class StateSnapshotOut(BaseModel):
    character_state: CharacterStateOut
    relationship_state: RelationshipStateOut
    emotion_history: list[EmotionHistoryItem]


class MessageItemOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class ConversationMessagesOut(BaseModel):
    conversation_id: str
    messages: list[MessageItemOut]


class MemoryItemOut(BaseModel):
    id: str
    user_id: str
    memory: str
    memory_type: str
    importance: float
    created_at: datetime
    updated_at: datetime


class MemoriesOut(BaseModel):
    user_id: str
    memories: list[MemoryItemOut]
