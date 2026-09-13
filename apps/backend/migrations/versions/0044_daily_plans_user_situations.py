"""WS-002 V2.3.0 世界模拟：daily_plans / user_situations 两表。

Revision ID: 0044
Revises: 0043
Create Date: 2026-09-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_plans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("part_of_day", sa.String(), nullable=False),
        sa.Column("start_minutes", sa.Integer(), nullable=False),
        sa.Column("end_minutes", sa.Integer(), nullable=False),
        sa.Column("activity", sa.String(50), nullable=False),
        sa.Column("location_id", sa.String(50), nullable=False),
        sa.Column("variability_source", sa.String(), nullable=False, server_default="fixed"),
        sa.Column("status", sa.String(), nullable=False, server_default="planned"),
        sa.Column("routine_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "part_of_day IN ('morning', 'afternoon', 'dusk', 'evening', 'late_night')",
            name="ck_daily_plans_part_of_day",
        ),
        sa.CheckConstraint(
            "variability_source IN ('fixed', 'variant', 'user_influenced')",
            name="ck_daily_plans_variability",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'completed', 'skipped', 'superseded')",
            name="ck_daily_plans_status",
        ),
    )
    op.create_index(
        "idx_daily_plans_lookup",
        "daily_plans",
        ["user_id", "plan_date", "status"],
    )
    op.create_index(
        "uq_daily_plans_user_date_seq",
        "daily_plans",
        ["user_id", "plan_date", "seq"],
        unique=True,
        sqlite_where=sa.text("status IN ('planned', 'active')"),
        postgresql_where=sa.text("status IN ('planned', 'active')"),
    )

    op.create_table(
        "user_situations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("dimension", sa.String(30), nullable=False),
        sa.Column("summary", sa.String(100), nullable=False),
        sa.Column("intensity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("source", sa.String(), nullable=False, server_default="conversation_pattern"),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("intensity BETWEEN 1 AND 5", name="ck_user_situations_intensity"),
        sa.CheckConstraint(
            "status IN ('active', 'expired', 'dismissed')",
            name="ck_user_situations_status",
        ),
        sa.CheckConstraint(
            "source IN ('conversation_pattern', 'user_directive', 'llm_assist')",
            name="ck_user_situations_source",
        ),
    )
    op.create_index(
        "idx_user_situations_active",
        "user_situations",
        ["user_id", "status", "valid_until"],
    )


def downgrade() -> None:
    op.drop_index("uq_daily_plans_user_date_seq", table_name="daily_plans")
    op.drop_index("idx_daily_plans_lookup", table_name="daily_plans")
    op.drop_table("daily_plans")
    op.drop_index("idx_user_situations_active", table_name="user_situations")
    op.drop_table("user_situations")
