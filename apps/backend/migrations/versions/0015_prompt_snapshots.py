"""prompt_snapshots 表（V7.8-004，风格对齐 0012）。

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.Column("call_site", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("section_budget", sa.JSON(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_prompt_snapshots_turn", "prompt_snapshots", ["turn_id"])
    op.create_index("idx_prompt_snapshots_request", "prompt_snapshots", ["request_id"])
    op.create_index("idx_prompt_snapshots_time", "prompt_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_prompt_snapshots_time", table_name="prompt_snapshots")
    op.drop_index("idx_prompt_snapshots_request", table_name="prompt_snapshots")
    op.drop_index("idx_prompt_snapshots_turn", table_name="prompt_snapshots")
    op.drop_table("prompt_snapshots")
