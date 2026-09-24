"""API-005 轻量任务域 life_tasks（唯一新表）。

Revision ID: 0055
Revises: 0054
Create Date: 2026-09-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "life_tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="task"),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("tag", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("order_reason", sa.String(), nullable=True),
        sa.Column("remind_at", sa.DateTime(), nullable=True),
        sa.Column("due_date", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('task', 'memo')",
            name="ck_life_tasks_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'done', 'cancelled')",
            name="ck_life_tasks_status",
        ),
    )
    op.create_index("ix_life_tasks_user_status", "life_tasks", ["user_id", "status"])
    op.create_index("ix_life_tasks_user_remind", "life_tasks", ["user_id", "remind_at"])


def downgrade() -> None:
    op.drop_index("ix_life_tasks_user_remind", table_name="life_tasks")
    op.drop_index("ix_life_tasks_user_status", table_name="life_tasks")
    op.drop_table("life_tasks")
