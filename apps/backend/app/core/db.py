from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    false,
    text,
)
from sqlalchemy import types as sa_types
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.settings import get_settings


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="default", server_default="default"
    )
    mode_entered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "mode IN ('professional', 'default', 'immersive')",
            name="ck_conversations_mode",
        ),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_proactive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('human', 'ai')", name="ck_messages_role"),
        Index("idx_messages_conv", "conversation_id", "created_at"),
    )


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class VectorType(sa_types.UserDefinedType):
    """pgvector 向量列类型；SQLite 下退化为 JSON 存储（仅保证迁移可跑，不启用向量检索）。"""

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "VECTOR(768)"

    def bind_processor(self, dialect):
        if dialect.name == "sqlite":
            return lambda value: value
        return None

    def result_processor(self, dialect, coltype):
        return None


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="*", server_default="*"
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="ai_inferred", server_default="ai_inferred"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    embedding: Mapped[object | None] = mapped_column(VectorType, nullable=True)
    salience: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_reinforced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_decayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    forgotten_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    merge_chain: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('user_preference', 'user_fact', 'important_event',"
            " 'relationship_event', 'experience', 'relationship_fact',"
            " 'commitment', 'milestone_event', 'behavior_pattern')",
            name="ck_memories_type",
        ),
        Index("idx_memories_user", "user_id"),
        Index(
            "idx_memories_user_character_status",
            "user_id",
            "character_id",
            "status",
        ),
    )


class RelationshipMilestoneRow(Base):
    __tablename__ = "relationship_milestones"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    milestone_key: Mapped[str] = mapped_column(String, nullable=False)
    period_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    title: Mapped[str] = mapped_column(String, nullable=False, default="")
    applied_bonus: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    unlocks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "milestone_key",
            "period_key",
            name="uq_relationship_milestones_user_key_period",
        ),
        Index("idx_relationship_milestones_user", "user_id", "created_at"),
    )


class RelationshipConflictRow(Base):
    __tablename__ = "relationship_conflicts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    status: Mapped[str] = mapped_column(String, nullable=False)
    trigger_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_negative_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recovery_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('strain', 'conflict', 'cold', 'recovery', 'resolved')",
            name="ck_relationship_conflicts_status",
        ),
        Index("idx_relationship_conflicts_user_status", "user_id", "status"),
    )


class RelationshipEventRow(Base):
    __tablename__ = "relationship_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    magnitude: Mapped[str] = mapped_column(String, nullable=False)
    impact_intimacy: Mapped[float] = mapped_column(Float, nullable=False)
    impact_trust: Mapped[float] = mapped_column(Float, nullable=False)
    impact_familiarity: Mapped[float] = mapped_column(Float, nullable=False)
    impact_respect: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    impact_comfort: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    impact_tension: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="conversation", server_default="conversation"
    )
    cause: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "type IN ('user_care', 'user_help', 'intimate_moment', 'long_interaction',"
            " 'praise', 'warm_moment', 'criticized', 'conflict', 'boundary_violation',"
            " 'promise_kept', 'promise_broken', 'none')",
            name="ck_relationship_events_type",
        ),
        CheckConstraint(
            "magnitude IN ('weak', 'normal', 'strong')",
            name="ck_relationship_events_magnitude",
        ),
        CheckConstraint(
            "source IN ('conversation', 'memory_replay', 'system')",
            name="ck_relationship_events_source",
        ),
        Index("idx_relationship_events_user", "user_id", "created_at"),
    )


class CharacterStateRow(Base):
    __tablename__ = "character_state"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    mood: Mapped[str] = mapped_column(String, nullable=False)
    energy: Mapped[float] = mapped_column(Float, nullable=False)
    current_topic: Mapped[str] = mapped_column(String, nullable=False, default="")
    inner_state: Mapped[str] = mapped_column(Text, nullable=False)
    intensity: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.3, server_default="0.3"
    )
    cause: Mapped[str] = mapped_column(
        String, nullable=False, default="", server_default=""
    )
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "mood IN ('happy', 'calm', 'worried', 'sad', 'shy', 'excited', 'tired', 'angry')",
            name="ck_character_state_mood",
        ),
    )


class RelationshipStateRow(Base):
    __tablename__ = "relationship_state"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    intimacy: Mapped[float] = mapped_column(Float, nullable=False)
    trust: Mapped[float] = mapped_column(Float, nullable=False)
    familiarity: Mapped[float] = mapped_column(Float, nullable=False)
    respect: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.6, server_default="0.6"
    )
    comfort: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.6, server_default="0.6"
    )
    tension: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    conflict_status: Mapped[str] = mapped_column(
        String, nullable=False, default="none", server_default="none"
    )
    neglect_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('stranger', 'friend', 'close_friend', 'partner')",
            name="ck_relationship_state_stage",
        ),
        CheckConstraint(
            "conflict_status IN ('none', 'strain', 'conflict', 'cold', 'recovery',"
            " 'resolved')",
            name="ck_relationship_state_conflict_status",
        ),
    )


class SceneStateRow(Base):
    __tablename__ = "scene_state"

    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    turn_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    current_activity: Mapped[str | None] = mapped_column(String, nullable=True)
    current_action: Mapped[str | None] = mapped_column(String, nullable=True)
    pending_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_actions: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class GoalRow(Base):
    __tablename__ = "character_goals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    horizon: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_turn: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    parent_goal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    layer: Mapped[str | None] = mapped_column(String, nullable=True)
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    origin: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    arbitration_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('user_care', 'relationship', 'conversation', 'scene')",
            name="ck_character_goals_type",
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'expired', 'cancelled',"
            " 'failed', 'suspended', 'abandoned')",
            name="ck_character_goals_status",
        ),
        CheckConstraint(
            "horizon IN ('persistent', 'current')",
            name="ck_character_goals_horizon",
        ),
        CheckConstraint(
            "source IN ('definition', 'policy', 'scene')",
            name="ck_character_goals_source",
        ),
        CheckConstraint(
            "layer IN ('short_term', 'medium', 'long_term') OR layer IS NULL",
            name="ck_character_goals_layer",
        ),
        CheckConstraint(
            "domain IN ('personal', 'relationship', 'world') OR domain IS NULL",
            name="ck_character_goals_domain",
        ),
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_character_goals_priority"),
        Index("idx_character_goals_user_status", "user_id", "status"),
        Index("idx_character_goals_parent", "parent_goal_id"),
        Index("idx_character_goals_layer_domain", "layer", "domain"),
    )


class GoalPlanRow(Base):
    __tablename__ = "goal_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    goal_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="draft", server_default="draft"
    )
    sub_goals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("goal_id", "version", name="uq_goal_plans_goal_version"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'active', 'rejected', 'superseded')",
            name="ck_goal_plans_status",
        ),
        Index("idx_goal_plans_goal_status", "goal_id", "status"),
    )


class EmotionHistoryRow(Base):
    __tablename__ = "emotion_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    user_emotion: Mapped[str] = mapped_column(String, nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    behavior: Mapped[str] = mapped_column(String, nullable=False)
    mood_before: Mapped[str] = mapped_column(String, nullable=False)
    mood_after: Mapped[str] = mapped_column(String, nullable=False)
    energy_after: Mapped[float] = mapped_column(Float, nullable=False)
    stage_after: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_emotion_history_user", "user_id", "created_at"),
    )


def create_engine_from_url(url: str | None = None):
    database_url = url or get_settings().database_url
    if database_url.startswith("sqlite"):
        return create_engine(database_url, connect_args={"check_same_thread": False})
    if not database_url.startswith("postgresql"):
        raise ValueError(f"不支持的数据库 URL：{database_url}")
    settings = get_settings()
    return create_engine(
        database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=settings.db_pool_pre_ping,
    )


engine = create_engine_from_url()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)




class ProactiveActionRow(Base):
    __tablename__ = "proactive_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False)
    goal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    intention: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    payload_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "type IN ('send_message')",
            name="ck_proactive_actions_type",
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'delivered', 'acked',"
            " 'discarded', 'failed', 'expired')",
            name="ck_proactive_actions_status",
        ),
        CheckConstraint(
            "trigger_type IN ('conversation_inactivity', 'scheduled_followup')",
            name="ck_proactive_actions_trigger_type",
        ),
        Index("idx_proactive_actions_user_status", "user_id", "status"),
        Index("idx_proactive_actions_dedupe", "dedupe_key"),
    )


class PromptSnapshotRow(Base):
    __tablename__ = "prompt_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, nullable=False)
    turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    call_site: Mapped[str] = mapped_column(String, nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    messages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    section_budget: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_prompt_snapshots_turn", "turn_id"),
        Index("idx_prompt_snapshots_request", "request_id"),
        Index("idx_prompt_snapshots_time", "created_at"),
    )


class LlmCallRecordRow(Base):
    __tablename__ = "llm_call_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    call_site: Mapped[str] = mapped_column(String, nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ttft_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('ok', 'error')",
            name="ck_llm_call_records_status",
        ),
        Index("idx_llm_calls_request", "request_id"),
        Index("idx_llm_calls_turn", "turn_id"),
        Index("idx_llm_calls_time", "created_at"),
    )


class DecisionRecordRow(Base):
    __tablename__ = "decision_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action_id: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger: Mapped[str | None] = mapped_column(String, nullable=True)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    candidates: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('proactive_autonomy', 'turn_goal', 'turn_intention',"
            " 'turn_behavior', 'goal_lifecycle')",
            name="ck_decision_records_kind",
        ),
        Index("idx_decision_records_user_time", "user_id", "kind", "created_at"),
        Index("idx_decision_records_action", "action_id"),
    )


class WorldRow(Base):
    __tablename__ = "worlds"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="home", server_default="home")
    time_mode: Mapped[str] = mapped_column(String, nullable=False, default="real_sync", server_default="real_sync")
    sim_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sim_last_advanced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sim_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    current_location: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "time_mode IN ('real_sync', 'simulated', 'story')",
            name="ck_worlds_time_mode",
        ),
    )


class WorldEntityRow(Base):
    __tablename__ = "world_entities"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    world_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    category: Mapped[str] = mapped_column(String, nullable=False)
    location_id: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    unit: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    consumable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    properties: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", server_default="active")
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "category IN ('food', 'drink', 'tool', 'furniture', 'clothing', 'device', 'misc')",
            name="ck_world_entities_category",
        ),
        CheckConstraint(
            "status IN ('active', 'destroyed')",
            name="ck_world_entities_status",
        ),
        Index("idx_world_entities_world_location", "world_id", "location_id"),
        Index("idx_world_entities_world_status", "world_id", "status"),
    )


class ActionRecordRow(Base):
    __tablename__ = "action_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="conversation")
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    intent: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    goal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False, default="")
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    gate_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('created', 'planned', 'executing', 'succeeded', 'failed', 'cancelled')",
            name="ck_action_records_status",
        ),
        CheckConstraint(
            "source IN ('conversation', 'autonomy', 'cancel')",
            name="ck_action_records_source",
        ),
        Index("idx_action_records_user_status", "user_id", "status"),
        Index("idx_action_records_user_dedupe", "user_id", "dedupe_key"),
    )


class WorldEventRow(Base):
    __tablename__ = "world_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    world_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    importance: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String, nullable=False, default="user_mention", server_default="user_mention")
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "importance IN ('low', 'normal', 'high')",
            name="ck_world_events_importance",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'active', 'completed', 'cancelled', 'expired')",
            name="ck_world_events_status",
        ),
        CheckConstraint(
            "source IN ('user_mention', 'manual', 'autonomy', 'character', "
            "'time', 'weather', 'calendar', 'user_evidence', 'daily_life', 'simulation')",
            name="ck_world_events_source",
        ),
        Index(
            "uq_world_events_idempotency",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("idx_world_events_world_due", "world_id", "status", "due_at"),
    )


class WorldSnapshotRow(Base):
    __tablename__ = "world_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    world_id: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_world_snapshots_world_time", "world_id", "created_at"),
    )


class DailyPlanRow(Base):
    __tablename__ = "daily_plans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    part_of_day: Mapped[str] = mapped_column(String, nullable=False)
    start_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    activity: Mapped[str] = mapped_column(String(50), nullable=False)
    location_id: Mapped[str] = mapped_column(String(50), nullable=False)
    variability_source: Mapped[str] = mapped_column(String, nullable=False, default="fixed", server_default="fixed")
    status: Mapped[str] = mapped_column(String, nullable=False, default="planned", server_default="planned")
    routine_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "part_of_day IN ('morning', 'afternoon', 'dusk', 'evening', 'late_night')",
            name="ck_daily_plans_part_of_day",
        ),
        CheckConstraint(
            "variability_source IN ('fixed', 'variant', 'user_influenced')",
            name="ck_daily_plans_variability",
        ),
        CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'skipped', 'superseded')",
            name="ck_daily_plans_status",
        ),
        Index(
            "uq_daily_plans_user_date_seq",
            "user_id",
            "plan_date",
            "seq",
            unique=True,
            sqlite_where=text("status IN ('planned', 'active')"),
            postgresql_where=text("status IN ('planned', 'active')"),
        ),
        Index("idx_daily_plans_lookup", "user_id", "plan_date", "status"),
    )


class UserSituationRow(Base):
    __tablename__ = "user_situations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    dimension: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[str] = mapped_column(String(100), nullable=False)
    intensity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", server_default="active")
    source: Mapped[str] = mapped_column(String, nullable=False, default="conversation_pattern", server_default="conversation_pattern")
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "intensity BETWEEN 1 AND 5",
            name="ck_user_situations_intensity",
        ),
        CheckConstraint(
            "status IN ('active', 'expired', 'dismissed')",
            name="ck_user_situations_status",
        ),
        CheckConstraint(
            "source IN ('conversation_pattern', 'user_directive', 'llm_assist')",
            name="ck_user_situations_source",
        ),
        Index("idx_user_situations_active", "user_id", "status", "valid_until"),
    )


class RuntimeTraceRow(Base):
    __tablename__ = "runtime_traces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    action_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    token_usage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('turn', 'proactive', 'autonomy_tick')",
            name="ck_runtime_traces_kind",
        ),
        Index("idx_runtime_traces_turn", "turn_id"),
        Index("idx_runtime_traces_user_time", "user_id", "created_at"),
        Index("idx_runtime_traces_conversation", "conversation_id", "created_at"),
    )


class RelationshipSnapshotRow(Base):
    __tablename__ = "relationship_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    conflict_status: Mapped[str] = mapped_column(
        String, nullable=False, default="none", server_default="none"
    )
    trigger: Mapped[str] = mapped_column(
        String, nullable=False, default="manual", server_default="manual"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('stranger', 'friend', 'close_friend', 'partner')",
            name="ck_relationship_snapshots_stage",
        ),
        CheckConstraint(
            "conflict_status IN ('none', 'strain', 'conflict', 'cold', 'recovery',"
            " 'resolved')",
            name="ck_relationship_snapshots_conflict_status",
        ),
        Index(
            "idx_relationship_snapshots_user_version",
            "user_id",
            "version",
            unique=False,
        ),
    )


class EvaluationReportRow(Base):
    __tablename__ = "evaluation_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, nullable=False)
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    issues: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    context_digest: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "subject IN ('turn', 'proactive_action', 'offline_batch')",
            name="ck_evaluation_reports_subject",
        ),
        CheckConstraint(
            "verdict IN ('pass', 'warn', 'fail')",
            name="ck_evaluation_reports_verdict",
        ),
        Index("idx_evaluation_user_time", "user_id", "created_at"),
        Index("idx_evaluation_subject", "subject", "subject_id"),
    )


class MemoryCandidateRow(Base):
    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="*", server_default="*"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_type: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_table: Mapped[str | None] = mapped_column(String, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    salience: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    visibility: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'promoted')",
            name="ck_memory_candidates_status",
        ),
        UniqueConstraint("source_table", "source_id", name="uq_memory_candidates_source"),
        Index("idx_memory_candidates_user_status", "user_id", "status"),
    )


class MemoryLinkRow(Base):
    __tablename__ = "memory_links"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(String, nullable=False)
    related_memory_id: Mapped[str] = mapped_column(String, nullable=False)
    relation: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "relation IN ('supersedes', 'merges', 'contradicts')",
            name="ck_memory_links_relation",
        ),
        Index("idx_memory_links_memory", "memory_id"),
    )


class InsightRow(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'invalidated')",
            name="ck_insights_status",
        ),
        CheckConstraint(
            "type IN ('belief', 'preference', 'pattern',"
            " 'capability_note', 'usage_preference', 'interaction_calibration')",
            name="ck_insights_type",
        ),
        CheckConstraint(
            "scope IN ('user', 'relationship', 'world')",
            name="ck_insights_scope",
        ),
        CheckConstraint(
            "status != 'invalidated' OR invalidated_reason IS NOT NULL",
            name="ck_insights_invalidated_reason",
        ),
        Index("idx_insights_user_status", "user_id", "status"),
        Index("idx_insights_user_scope_status", "user_id", "scope", "status"),
    )


class ReflectionRunRow(Base):
    __tablename__ = "reflection_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="queued", server_default="queued"
    )
    evidence_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    insight_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'skipped', 'failed')",
            name="ck_reflection_runs_status",
        ),
        CheckConstraint(
            "trigger IN ('scheduled', 'event')",
            name="ck_reflection_runs_trigger",
        ),
        Index("idx_reflection_runs_user_status", "user_id", "status"),
        Index("idx_reflection_runs_status_created", "status", "created_at"),
    )


class EvidenceLinkRow(Base):
    __tablename__ = "evidence_links"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    insight_id: Mapped[str] = mapped_column(String, nullable=False)
    memory_id: Mapped[str] = mapped_column(String, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("insight_id", "memory_id", name="uq_evidence_links_insight_memory"),
        Index("idx_evidence_links_memory", "memory_id"),
    )


class BackgroundJobRow(Base):
    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_background_jobs_status",
        ),
        Index("idx_background_jobs_status_run_at", "status", "run_at"),
    )


class TriggerRegistryRow(Base):
    __tablename__ = "trigger_registry"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    trigger_type: Mapped[str] = mapped_column(String, nullable=False)
    trigger_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('conversation_inactivity', 'scheduled_followup', 'action_due')",
            name="ck_trigger_registry_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'due', 'fired', 'done', 'cancelled')",
            name="ck_trigger_registry_status",
        ),
        Index("idx_trigger_registry_status_due_at", "status", "due_at"),
        Index("idx_trigger_registry_user_status", "user_id", "status"),
    )


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(
        String, nullable=False, default="action_result", server_default="action_result"
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'consumed', 'failed')",
            name="ck_outbox_events_status",
        ),
        Index("idx_outbox_events_status_next_retry", "status", "next_retry_at"),
    )


class LoopRunRow(Base):
    __tablename__ = "loop_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    run_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trigger_id: Mapped[str | None] = mapped_column(String, nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="running", server_default="running"
    )
    current_step: Mapped[str | None] = mapped_column(String, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    llm_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('autonomy', 'chat', 'world_maintenance', 'action_retry', "
            "'outbox_consume', 'trigger_reconcile')",
            name="ck_loop_runs_kind",
        ),
        CheckConstraint(
            "status IN ('running', 'done', 'aborted', 'degraded')",
            name="ck_loop_runs_status",
        ),
        Index("idx_loop_runs_status_started_at", "status", "started_at"),
        Index("idx_loop_runs_user_started_at", "user_id", "started_at"),
    )


class DevelopmentStateRow(Base):
    __tablename__ = "development_state"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(
        String, nullable=False, default="asuna", server_default="asuna"
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    strength: Mapped[float] = mapped_column(Float, nullable=False)
    source_insight_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'retired')",
            name="ck_development_state_status",
        ),
        CheckConstraint(
            "kind IN ('belief', 'preference', 'pattern')",
            name="ck_development_state_kind",
        ),
        CheckConstraint(
            "strength >= 0 AND strength <= 1",
            name="ck_development_state_strength",
        ),
        Index("idx_development_state_user_status", "user_id", "status"),
        Index("idx_development_state_user_kind", "user_id", "kind", "status"),
    )


class DevelopmentChangeRow(Base):
    __tablename__ = "development_changes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    development_state_id: Mapped[str | None] = mapped_column(String, nullable=True)
    personality_state_id: Mapped[str | None] = mapped_column(String, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    insight_id: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False, default="compiled", server_default="compiled")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "reason IN ('compiled', 'arbitrated', 'arbitrated_lost',"
            " 'rolled_back', 'retired', 'replayed', 'personality')",
            name="ck_development_changes_reason",
        ),
        Index("idx_development_changes_state", "development_state_id"),
        Index("idx_development_changes_insight", "insight_id"),
    )


class ChannelIdentityRow(Base):
    __tablename__ = "channel_identities"

    channel: Mapped[str] = mapped_column(String, nullable=False, primary_key=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False, primary_key=True)
    internal_user_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    external_union_id: Mapped[str | None] = mapped_column(String, nullable=True)
    external_tenant_key: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("channel", "external_id"),
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_channel_identities_status",
        ),
        Index("idx_channel_identities_user", "internal_user_id"),
    )


class PersonalityStateRow(Base):
    __tablename__ = "personality_state"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    axis: Mapped[str] = mapped_column(String, nullable=False)
    baseline: Mapped[float] = mapped_column(Float, nullable=False)
    current: Mapped[float] = mapped_column(Float, nullable=False)
    bound_min: Mapped[float] = mapped_column(Float, nullable=False)
    bound_max: Mapped[float] = mapped_column(Float, nullable=False)
    source_insight_id: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "character_id",
            "axis",
            name="uq_personality_state_axis",
        ),
    )


class AgentStateSnapshotRow(Base):
    __tablename__ = "agent_state_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("idx_agent_state_snapshots_user_created", "user_id", "created_at"),
    )


class AgentMetricSnapshotRow(Base):
    __tablename__ = "agent_metric_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trend: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "character_id",
            "window_start",
            name="uq_agent_metric_window",
        ),
    )
