"""memories v4 columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_TYPE_BACKFILL_SQL = """
UPDATE memories
SET memory_type = CASE memory_type
    WHEN 'preference' THEN 'user_preference'
    WHEN 'fact' THEN 'user_fact'
    WHEN 'goal' THEN 'user_fact'
    WHEN 'experience' THEN 'important_event'
    WHEN 'relationship' THEN 'relationship_event'
    ELSE memory_type
END
"""


def upgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.add_column(
            sa.Column("character_id", sa.String(), nullable=False, server_default="*")
        )
        batch.add_column(
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column(
                "source",
                sa.String(),
                nullable=False,
                server_default="ai_inferred",
            )
        )
        batch.add_column(
            sa.Column("status", sa.String(), nullable=False, server_default="active")
        )
        batch.add_column(sa.Column("superseded_by", sa.String(), nullable=True))
        batch.add_column(sa.Column("last_accessed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))
        batch.drop_constraint("ck_memories_memory_type", type_="check")
        batch.create_check_constraint(
            "ck_memories_memory_type",
            "memory_type IN ('preference', 'fact', 'goal', 'experience', 'relationship',"
            " 'user_preference', 'user_fact', 'important_event', 'relationship_event')",
        )
    op.execute(LEGACY_TYPE_BACKFILL_SQL)
    op.create_index(
        "idx_memories_user_character_status",
        "memories",
        ["user_id", "character_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_memories_user_character_status", table_name="memories")
    with op.batch_alter_table("memories") as batch:
        batch.drop_constraint("ck_memories_memory_type", type_="check")
        batch.create_check_constraint(
            "ck_memories_memory_type",
            "memory_type IN ('preference', 'fact', 'goal', 'experience', 'relationship')",
        )
        batch.drop_column("expires_at")
        batch.drop_column("last_accessed_at")
        batch.drop_column("superseded_by")
        batch.drop_column("status")
        batch.drop_column("source")
        batch.drop_column("confidence")
        batch.drop_column("character_id")
