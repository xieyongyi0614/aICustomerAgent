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


class BehaviorBudgetOut(BaseModel):
    max_action_desc: int
    allow_action_desc: bool
    physical_contact: str
    emotion_expression: str


class ModeMetaOut(BaseModel):
    confirmed: str
    effective: str
    switched: bool


class LastBehaviorOut(BaseModel):
    strategy: str
    base_strategy: str
    budget: BehaviorBudgetOut
    degraded: bool
    mode: ModeMetaOut | None = None


class StateSnapshotOut(BaseModel):
    character_state: CharacterStateOut
    relationship_state: RelationshipStateOut
    emotion_history: list[EmotionHistoryItem]
    relationship_events: list[RelationshipEventItem] = []
    mode: str | None = None
    last_behavior: LastBehaviorOut | None = None


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


class ProactiveActionOut(BaseModel):
    id: str
    intention: str
    reason: str = ""
    text: str
    session_id: str
    delivered_at: datetime | None = None


class ProactivePendingOut(BaseModel):
    actions: list[ProactiveActionOut] = []


class WorldBriefPartsOut(BaseModel):
    text: str = ""
    time_line: str | None = None
    place_line: str | None = None
    situations_line: str | None = None
    events_line: str | None = None


class WorldBriefOut(BaseModel):
    text: str = ""
    parts: WorldBriefPartsOut | None = None


class WorldSimPlanBlockOut(BaseModel):
    seq: int
    part_of_day: str
    start_minutes: int
    end_minutes: int
    activity: str
    location_id: str
    variability_source: str | None = None
    status: str
    note: str | None = None


class WorldSimSituationOut(BaseModel):
    dimension: str
    summary: str
    intensity: int
    status: str
    source: str
    detected_at: datetime | None = None
    valid_until: datetime | None = None
    evidence: dict = {}


class WorldSimEventOut(BaseModel):
    id: str
    type: str
    title: str
    importance: str
    status: str
    idempotency_key: str | None = None
    created_at: datetime | None = None


class WorldSimulationOut(BaseModel):
    enabled: bool
    time_context: dict | None = None
    brief: WorldBriefOut | None = None
    current_block: WorldSimPlanBlockOut | None = None
    active_situations: list[WorldSimSituationOut] = []
    recent_events: list[WorldSimEventOut] = []
    flags: dict = {}
    event_quota_drops: dict = {}


class WorldPlanOut(BaseModel):
    enabled: bool
    date: str | None = None
    blocks: list[WorldSimPlanBlockOut] = []


class WorldSituationsOut(BaseModel):
    enabled: bool
    situations: list[WorldSimSituationOut] = []


class WorldSimTickOut(BaseModel):
    enabled: bool
    result: dict | None = None
