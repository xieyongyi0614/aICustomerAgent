"""目标域模型：目标栈与目标规划。"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, UtcDateTime


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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
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
            "domain IN ('personal', 'relationship', 'world', 'budget') OR domain IS NULL",
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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("goal_id", "version", name="uq_goal_plans_goal_version"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'active', 'rejected', 'superseded')",
            name="ck_goal_plans_status",
        ),
        Index("idx_goal_plans_goal_status", "goal_id", "status"),
    )
