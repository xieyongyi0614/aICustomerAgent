"""proactive_actions 表 + messages.is_proactive（V7-002，对齐 0008 风格）。

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proactive_actions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "character_id", sa.String(), nullable=False, server_default="asuna"
        ),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("trigger_type", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=True),
        sa.Column("intention", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False, server_default=""),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "type IN ('send_message')",
            name="ck_proactive_actions_type",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'delivered', 'acked',"
            " 'discarded', 'failed', 'expired')",
            name="ck_proactive_actions_status",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('conversation_inactivity', 'scheduled_followup')",
            name="ck_proactive_actions_trigger_type",
        ),
    )
    op.create_index(
        "idx_proactive_actions_user_status",
        "proactive_actions",
        ["user_id", "status"],
    )
    op.create_index(
        "idx_proactive_actions_dedupe",
        "proactive_actions",
        ["dedupe_key"],
    )
    op.add_column(
        "messages",
        sa.Column(
            "is_proactive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="主动消息标记（V7 Autonomy Executor 写入，非对话轮）",
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "is_proactive")
    op.drop_index("idx_proactive_actions_dedupe", table_name="proactive_actions")
    op.drop_index(
        "idx_proactive_actions_user_status", table_name="proactive_actions"
    )
    op.drop_table("proactive_actions")
