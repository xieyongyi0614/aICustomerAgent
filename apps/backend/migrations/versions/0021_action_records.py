"""V9 action_records 表：行动审计存储（V9-004，M11）。

设计文档指定迁移编号 0018，但仓库链尾已至 0020（V8.5 占用 0018~0020），
按迁移序列顺延为 0021。

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="conversation"),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("intent", sa.JSON(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=True),
        sa.Column("target_record_id", sa.String(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=False, server_default=""),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="created"),
        sa.Column("gate_reason", sa.String(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('created', 'planned', 'executing', 'succeeded', 'failed', 'cancelled')",
            name="ck_action_records_status",
        ),
        sa.CheckConstraint(
            "source IN ('conversation', 'autonomy', 'cancel')",
            name="ck_action_records_source",
        ),
    )
    op.create_index(
        "idx_action_records_user_status",
        "action_records",
        ["user_id", "status"],
    )
    op.create_index(
        "idx_action_records_user_dedupe",
        "action_records",
        ["user_id", "dedupe_key"],
    )


def downgrade() -> None:
    op.drop_index("idx_action_records_user_dedupe", table_name="action_records")
    op.drop_index("idx_action_records_user_status", table_name="action_records")
    op.drop_table("action_records")
