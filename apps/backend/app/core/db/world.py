"""世界模拟域模型：世界、实体、事件、快照、日程与用户处境。"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    Index,
    Integer,
    JSON,
    String,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, UtcDateTime


class WorldRow(Base):
    __tablename__ = "worlds"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="home", server_default="home")
    time_mode: Mapped[str] = mapped_column(String, nullable=False, default="real_sync", server_default="real_sync")
    sim_time: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    sim_last_advanced_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    sim_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0, server_default="1")
    current_location: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    owner_type: Mapped[str | None] = mapped_column(String, nullable=True)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "time_mode IN ('real_sync', 'simulated', 'story')",
            name="ck_worlds_time_mode",
        ),
        Index("ix_worlds_owner", "owner_type", "owner_id"),
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
    last_action_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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


class WorldEventRow(Base):
    __tablename__ = "world_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    world_id: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    importance: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String, nullable=False, default="user_mention", server_default="user_mention")
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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
    detected_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

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
