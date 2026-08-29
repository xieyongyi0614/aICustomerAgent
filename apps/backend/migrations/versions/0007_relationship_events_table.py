"""relationship_events table

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "relationship_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("magnitude", sa.String(), nullable=False),
        sa.Column("impact_intimacy", sa.Float(), nullable=False),
        sa.Column("impact_trust", sa.Float(), nullable=False),
        sa.Column("impact_familiarity", sa.Float(), nullable=False),
        sa.Column("impact_tension", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("cause", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "type IN ('user_care', 'user_help', 'intimate_moment', 'long_interaction',"
            " 'praise', 'criticized', 'conflict', 'boundary_violation', 'none')",
            name="ck_relationship_events_type",
        ),
        sa.CheckConstraint(
            "magnitude IN ('weak', 'normal', 'strong')",
            name="ck_relationship_events_magnitude",
        ),
    )
    op.create_index(
        "idx_relationship_events_user",
        "relationship_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_relationship_events_user", table_name="relationship_events")
    op.drop_table("relationship_events")
