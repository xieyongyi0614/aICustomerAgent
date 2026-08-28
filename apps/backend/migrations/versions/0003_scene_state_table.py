"""scene state table

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scene_state",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("current_activity", sa.String(), nullable=True),
        sa.Column("current_action", sa.String(), nullable=True),
        sa.Column("pending_action", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("scene_state")
