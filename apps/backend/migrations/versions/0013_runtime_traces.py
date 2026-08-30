"""runtime_traces 表（V7.8-002，风格对齐 0012）。

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_traces",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.Column("action_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('turn', 'proactive', 'autonomy_tick')",
            name="ck_runtime_traces_kind",
        ),
    )
    op.create_index(
        "idx_runtime_traces_turn",
        "runtime_traces",
        ["turn_id"],
    )
    op.create_index(
        "idx_runtime_traces_user_time",
        "runtime_traces",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_runtime_traces_conversation",
        "runtime_traces",
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_runtime_traces_conversation", table_name="runtime_traces")
    op.drop_index("idx_runtime_traces_user_time", table_name="runtime_traces")
    op.drop_index("idx_runtime_traces_turn", table_name="runtime_traces")
    op.drop_table("runtime_traces")
