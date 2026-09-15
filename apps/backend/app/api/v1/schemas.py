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


class ToolHealthOut(BaseModel):
    consecutive_failures: int = 0
    failure_rate_window: float = 0.0
    tripped: bool = False
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None


class ToolSummaryOut(BaseModel):
    tool_id: str
    name: str
    namespace: str
    status: str
    side_effects: list[str] = []
    health: ToolHealthOut | None = None


class ToolWorldIntentOut(BaseModel):
    """`world.intent.submit` 接线状态（TOOL-007 §4.2）：未接线必须可见（status=not_wired）。"""

    tool_id: str
    status: str
    wired: bool = False
    writes: int = 0
    intent_types: list[str] = []
    note: str = ""


class ToolsOut(BaseModel):
    enabled: bool
    tools: list[ToolSummaryOut] = []
    runtime_disabled: list[str] = []
    world_intent: ToolWorldIntentOut | None = None
    capability_registry_flags: dict[str, bool] = {}
    capability_names: list[str] = []
    tool_surface_degrade_count: int = 0


class ToolDetailOut(BaseModel):
    enabled: bool
    tool_id: str | None = None
    definition: dict | None = None
    permission: dict | None = None
    health: ToolHealthOut | None = None
    recent_executions: list[dict] = []


class ToolSurfaceOut(BaseModel):
    enabled: bool
    run_kind: str | None = None
    run_kind_defaulted: bool = False
    tool_ids: list[str] = []
    excluded: list[dict] = []
    surface_hash: str | None = None


class ToolRuntimeStatusOut(BaseModel):
    enabled: bool
    tool_id: str | None = None
    effective_status: str | None = None
    runtime_disabled: bool = False


class ToolExecutionRowOut(BaseModel):
    record_id: str
    tool_id: str | None = None
    status: str
    permission: dict = {}
    duration_ms: int | None = None
    effects: list[dict] = []


class ToolExecutionsOut(BaseModel):
    enabled: bool
    user_id: str | None = None
    executions: list[ToolExecutionRowOut] = []


class ToolGrantOut(BaseModel):
    tool_id: str
    scope: list[str] = []
    source: str
    granted_at: datetime | None = None
    expires_at: datetime | None = None


class ToolPermissionsOut(BaseModel):
    enabled: bool
    user_id: str | None = None
    grants: list[ToolGrantOut] = []


class ToolConfirmationOut(BaseModel):
    request_id: str
    tool_id: str
    status: str
    dedupe_key: str = ""
    scope_required: list[str] = []
    prompt: str | None = None
    confirm_kind: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None


class ToolConfirmationsOut(BaseModel):
    enabled: bool
    user_id: str | None = None
    confirmations: list[ToolConfirmationOut] = []


class ToolConfirmationRevokeOut(BaseModel):
    enabled: bool
    request_id: str | None = None
    revoked: bool = False
    status: str | None = None


class ToolPermissionRevokeOut(BaseModel):
    enabled: bool
    user_id: str | None = None
    tool_id: str | None = None
    revoked: int = 0


class ToolManifestSkipOut(BaseModel):
    """单条清单跳过项（TOOL-011 §4.1）：文件 + 失败项 + 原因（不含凭据值）。"""

    file: str = ""
    tool_id: str | None = None
    rule: int | str | None = None
    reason: str = ""


class ToolManifestOut(BaseModel):
    """外部 API 声明投影：声明信息 + 凭据**变量名**（绝不含凭据值）。"""

    tool_id: str
    name: str
    description: str = ""
    when_to_use: str = ""
    http: dict = {}
    auth: dict = {}
    response_map: dict = {}
    permission: dict = {}
    side_effects: list[str] = []
    parameters: list[str] = []
    source_file: str = ""


class ToolManifestsOut(BaseModel):
    """清单加载报告（TOOL-011 §4.5）：loaded / skipped / reasons。"""

    enabled: bool
    path: str = ""
    loaded: list[str] = []
    skipped: list[ToolManifestSkipOut] = []
    total: int = 0
    manifests: list[ToolManifestOut] = []


class ToolExternalOut(BaseModel):
    enabled: bool
    allowed_hosts: list[str] = []
    host_whitelist_empty: bool = True
    tools: list[dict] = []


class ToolUserDefinedOut(BaseModel):
    enabled: bool
    registered: list[str] = []
    tools: list[dict] = []


class ToolUserDefinedRevokeOut(BaseModel):
    enabled: bool
    tool_id: str | None = None
    revoked: bool = False
    registered: list[str] = []
