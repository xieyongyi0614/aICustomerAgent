"""v2 state tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "character_state",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("mood", sa.String(), nullable=False),
        sa.Column("energy", sa.Float(), nullable=False),
        sa.Column("current_topic", sa.String(), nullable=False),
        sa.Column("inner_state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint(
            "mood IN ('happy', 'calm', 'worried', 'sad', 'shy', 'excited', 'tired', 'angry')",
            name="ck_character_state_mood",
        ),
    )
    op.create_table(
        "relationship_state",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("intimacy", sa.Float(), nullable=False),
        sa.Column("trust", sa.Float(), nullable=False),
        sa.Column("familiarity", sa.Float(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint(
            "stage IN ('stranger', 'friend', 'close_friend', 'partner')",
            name="ck_relationship_state_stage",
        ),
    )
    op.create_table(
        "emotion_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_emotion", sa.String(), nullable=False),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("behavior", sa.String(), nullable=False),
        sa.Column("mood_before", sa.String(), nullable=False),
        sa.Column("mood_after", sa.String(), nullable=False),
        sa.Column("energy_after", sa.Float(), nullable=False),
        sa.Column("stage_after", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_emotion_history_user", "emotion_history", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_emotion_history_user", table_name="emotion_history")
    op.drop_table("emotion_history")
    op.drop_table("relationship_state")
    op.drop_table("character_state")
