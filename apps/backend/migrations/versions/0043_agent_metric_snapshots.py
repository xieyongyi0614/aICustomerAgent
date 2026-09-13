"""AGENT-006 Agent Evaluation：agent_metric_snapshots 周期快照表（落地 V7.8-014 留白）。

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_metric_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("window_start", sa.DateTime(), nullable=False),
        sa.Column("window_end", sa.DateTime(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("trend", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "character_id", "window_start", name="uq_agent_metric_window"
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_metric_snapshots")
