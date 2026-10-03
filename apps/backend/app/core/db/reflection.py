"""反思域模型：洞察、反思运行与证据关联。"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


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
