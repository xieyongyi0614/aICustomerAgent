"""memories column rename and type vocabulary consolidation

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-29

memory -> content, memory_type -> type；check 约束收紧为仅四类。
0004 已完成旧词值归一，此处 UPDATE 仅作防御性兜底；
降级不做值的反向映射（goal/fact 合并不可逆）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_TYPE_BACKFILL_SQL = """
UPDATE memories
SET type = CASE type
    WHEN 'preference' THEN 'user_preference'
    WHEN 'fact' THEN 'user_fact'
    WHEN 'goal' THEN 'user_fact'
    WHEN 'experience' THEN 'important_event'
    WHEN 'relationship' THEN 'relationship_event'
    ELSE type
END
"""


def upgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.drop_constraint("ck_memories_memory_type", type_="check")
        batch.alter_column("memory", new_column_name="content")
        batch.alter_column("memory_type", new_column_name="type")
        batch.create_check_constraint(
            "ck_memories_type",
            "type IN ('user_preference', 'user_fact', 'important_event', 'relationship_event')",
        )
    op.execute(LEGACY_TYPE_BACKFILL_SQL)


def downgrade() -> None:
    with op.batch_alter_table("memories") as batch:
        batch.drop_constraint("ck_memories_type", type_="check")
        batch.alter_column("type", new_column_name="memory_type")
        batch.alter_column("content", new_column_name="memory")
        batch.create_check_constraint(
            "ck_memories_memory_type",
            "memory_type IN ('preference', 'fact', 'goal', 'experience', 'relationship',"
            " 'user_preference', 'user_fact', 'important_event', 'relationship_event')",
        )
