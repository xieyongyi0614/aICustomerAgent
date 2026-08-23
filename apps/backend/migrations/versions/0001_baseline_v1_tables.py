"""baseline v1 tables

Revision ID: 0001
Revises:
Create Date: 2026-08-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("role IN ('human', 'ai')", name="ck_messages_role"),
    )
    op.create_index("idx_messages_conv", "messages", ["conversation_id", "created_at"])
    op.create_table(
        "conversation_summaries",
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_table(
        "memories",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("memory", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "memory_type IN ('preference', 'fact', 'goal', 'experience', 'relationship')",
            name="ck_memories_memory_type",
        ),
    )
    op.create_index("idx_memories_user", "memories", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_memories_user", table_name="memories")
    op.drop_table("memories")
    op.drop_table("conversation_summaries")
    op.drop_index("idx_messages_conv", table_name="messages")
    op.drop_table("messages")
    op.drop_table("conversations")
