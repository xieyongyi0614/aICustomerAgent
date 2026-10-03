from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


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
        Index(
            "uq_development_state_active_key",
            "user_id",
            "key",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
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
        CheckConstraint(
            "development_state_id IS NOT NULL OR personality_state_id IS NOT NULL",
            name="ck_development_changes_subject",
        ),
        Index("idx_development_changes_state", "development_state_id"),
        Index("idx_development_changes_insight", "insight_id"),
    )
