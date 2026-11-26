"""关系域模型：关系状态、事件流、冲突、里程碑与快照。"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, UtcDateTime


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
        UtcDateTime, nullable=True
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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
            "source IN ('conversation', 'system')",
            name="ck_relationship_events_source",
        ),
        Index("idx_relationship_events_user", "user_id", "created_at"),
    )


class RelationshipConflictRow(Base):
    __tablename__ = "relationship_conflicts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    character_id: Mapped[str] = mapped_column(String, nullable=False, default="asuna")
    status: Mapped[str] = mapped_column(String, nullable=False)
    trigger_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_negative_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    recovery_started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    resolution: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('strain', 'conflict', 'cold', 'recovery', 'resolved')",
            name="ck_relationship_conflicts_status",
        ),
        Index("idx_relationship_conflicts_user_status", "user_id", "status"),
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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "milestone_key",
            "period_key",
            name="uq_relationship_milestones_user_key_period",
        ),
        Index("idx_relationship_milestones_user", "user_id", "created_at"),
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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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
