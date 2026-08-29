from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
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

    __table_args__ = (
        CheckConstraint(
            "type IN ('user_preference', 'user_fact', 'important_event', 'relationship_event')",
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
            " 'praise', 'criticized', 'conflict', 'boundary_violation', 'none')",
            name="ck_relationship_events_type",
        ),
        CheckConstraint(
            "magnitude IN ('weak', 'normal', 'strong')",
            name="ck_relationship_events_magnitude",
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
    tension: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    stage: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('stranger', 'friend', 'close_friend', 'partner')",
            name="ck_relationship_state_stage",
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

    __table_args__ = (
        CheckConstraint(
            "type IN ('user_care', 'relationship', 'conversation', 'scene')",
            name="ck_character_goals_type",
        ),
        CheckConstraint(
            "status IN ('active', 'completed', 'expired', 'cancelled')",
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
        CheckConstraint("priority BETWEEN 1 AND 5", name="ck_character_goals_priority"),
        Index("idx_character_goals_user_status", "user_id", "status"),
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


