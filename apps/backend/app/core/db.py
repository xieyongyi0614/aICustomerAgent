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
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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
    memory: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(String, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "memory_type IN ('preference', 'fact', 'goal', 'experience', 'relationship')",
            name="ck_memories_memory_type",
        ),
        Index("idx_memories_user", "user_id"),
    )


class CharacterStateRow(Base):
    __tablename__ = "character_state"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    mood: Mapped[str] = mapped_column(String, nullable=False)
    energy: Mapped[float] = mapped_column(Float, nullable=False)
    current_topic: Mapped[str] = mapped_column(String, nullable=False, default="")
    inner_state: Mapped[str] = mapped_column(Text, nullable=False)
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
    stage: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('stranger', 'friend', 'close_friend', 'partner')",
            name="ck_relationship_state_stage",
        ),
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


def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
