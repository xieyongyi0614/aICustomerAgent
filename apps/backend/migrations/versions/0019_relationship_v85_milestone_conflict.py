"""V8.5 里程碑与冲突表：relationship_milestones + relationship_conflicts（V8.5-004/005）。

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "relationship_milestones",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False),
        sa.Column("milestone_key", sa.String(), nullable=False),
        sa.Column("period_key", sa.String(), nullable=False, server_default=""),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("applied_bonus", sa.JSON(), nullable=False),
        sa.Column("unlocks", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "milestone_key",
            "period_key",
            name="uq_relationship_milestones_user_key_period",
        ),
    )
    op.create_index(
        "idx_relationship_milestones_user",
        "relationship_milestones",
        ["user_id", "created_at"],
    )
    op.create_table(
        "relationship_conflicts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger_event_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_negative_at", sa.DateTime(), nullable=True),
        sa.Column("recovery_started_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('strain', 'conflict', 'cold', 'recovery', 'resolved')",
            name="ck_relationship_conflicts_status",
        ),
    )
    op.create_index(
        "idx_relationship_conflicts_user_status",
        "relationship_conflicts",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_relationship_conflicts_user_status", table_name="relationship_conflicts"
    )
    op.drop_table("relationship_conflicts")
    op.drop_index(
        "idx_relationship_milestones_user", table_name="relationship_milestones"
    )
    op.drop_table("relationship_milestones")