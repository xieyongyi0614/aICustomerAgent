"""角色域模型：角色状态、情绪历史与人格轴。"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, UtcDateTime


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
    last_event_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "mood IN ('happy', 'calm', 'worried', 'sad', 'shy', 'excited', 'tired', 'angry')",
            name="ck_character_state_mood",
        ),
    )


class EmotionHistoryRow(Base):
    __tablename__ = "emotion_history"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=False,
    )
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    session_id: Mapped[str] = mapped_column(String, nullable=False)
    user_emotion: Mapped[str] = mapped_column(String, nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    behavior: Mapped[str] = mapped_column(String, nullable=False)
    mood_before: Mapped[str] = mapped_column(String, nullable=False)
    mood_after: Mapped[str] = mapped_column(String, nullable=False)
    energy_after: Mapped[float] = mapped_column(Float, nullable=False)
    stage_after: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        Index("idx_emotion_history_user", "user_id", "created_at"),
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
    updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "character_id",
            "axis",
            name="uq_personality_state_axis",
        ),
    )
