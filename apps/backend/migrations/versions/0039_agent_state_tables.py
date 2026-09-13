"""AGENT-002 Character State 表（personality_state + agent_state_snapshots）。

- personality_state：人格轴慢变量 SoT（AGENT-002 建基线，AGENT-005 唯一写入）。
- agent_state_snapshots：统一意识状态时点存档（投影存档，非真相源）。

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personality_state",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("axis", sa.String(), nullable=False),
        sa.Column("baseline", sa.Float(), nullable=False),
        sa.Column("current", sa.Float(), nullable=False),
        sa.Column("bound_min", sa.Float(), nullable=False),
        sa.Column("bound_max", sa.Float(), nullable=False),
        sa.Column("source_insight_id", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "character_id", "axis", name="uq_personality_state_axis"
        ),
    )
    op.create_table(
        "agent_state_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_agent_state_snapshots_user_created",
        "agent_state_snapshots",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_agent_state_snapshots_user_created", table_name="agent_state_snapshots"
    )
    op.drop_table("agent_state_snapshots")
    op.drop_table("personality_state")
