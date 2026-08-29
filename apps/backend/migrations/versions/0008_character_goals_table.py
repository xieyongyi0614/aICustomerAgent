"""character_goals table

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "character_goals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "character_id", sa.String(), nullable=False, server_default="asuna"
        ),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="active"
        ),
        sa.Column("horizon", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_turn", sa.Integer(), nullable=False),
        sa.Column("expires_at_turn", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "type IN ('user_care', 'relationship', 'conversation', 'scene')",
            name="ck_character_goals_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'expired', 'cancelled')",
            name="ck_character_goals_status",
        ),
        sa.CheckConstraint(
            "horizon IN ('persistent', 'current')",
            name="ck_character_goals_horizon",
        ),
        sa.CheckConstraint(
            "source IN ('definition', 'policy', 'scene')",
            name="ck_character_goals_source",
        ),
        sa.CheckConstraint("priority BETWEEN 1 AND 5", name="ck_character_goals_priority"),
    )
    op.create_index(
        "idx_character_goals_user_status",
        "character_goals",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_character_goals_user_status", table_name="character_goals")
    op.drop_table("character_goals")
