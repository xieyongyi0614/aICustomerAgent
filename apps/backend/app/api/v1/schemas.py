from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str | None = None
    content: str
    profile_id: str | None = Field(default=None, description="LLM profile id; falls back to default")


class ChatSessionResponse(BaseModel):
    session_id: str


class ChatDelta(BaseModel):
    delta: str


class ChatDone(BaseModel):
    done: bool = True


class LlmProfileOut(BaseModel):
    id: str
    label: str
    model: str
    default: bool


class LlmProfilesOut(BaseModel):
    default: str
    profiles: list[LlmProfileOut]


class CharacterStateOut(BaseModel):
    mood: str
    energy: float
    current_topic: str
    inner_state: str
    updated_at: datetime | None = None
    intensity: float = 0.3
    cause: str = ""
    last_event_at: datetime | None = None


class RelationshipStateOut(BaseModel):
    intimacy: float
    trust: float
    familiarity: float
    tension: float = 0.0
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


class RelationshipEventItem(BaseModel):
    type: str
    magnitude: str
    impact_intimacy: float
    impact_trust: float
    impact_familiarity: float
    impact_tension: float
    confidence: float
    source: str
    cause: str
    created_at: datetime


class StateSnapshotOut(BaseModel):
    character_state: CharacterStateOut
    relationship_state: RelationshipStateOut
    emotion_history: list[EmotionHistoryItem]
    relationship_events: list[RelationshipEventItem] = []


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
    character_id: str = "asuna"
    type: str | None = None
    confidence: float = 0.0
    source: str = "ai_inferred"
    status: str = "active"
    superseded_by: str | None = None


class MemoriesOut(BaseModel):
    user_id: str
    memories: list[MemoryItemOut]
