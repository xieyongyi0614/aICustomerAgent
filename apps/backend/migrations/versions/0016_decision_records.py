"""decision_records 表（V7.8-005，风格对齐 0012）。

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("action_id", sa.String(), nullable=True),
        sa.Column("trigger", sa.String(), nullable=True),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind IN ('proactive_autonomy', 'turn_goal', 'turn_intention', 'turn_behavior')",
            name="ck_decision_records_kind",
        ),
    )
    op.create_index(
        "idx_decision_records_user_time",
        "decision_records",
        ["user_id", "kind", "created_at"],
    )
    op.create_index("idx_decision_records_action", "decision_records", ["action_id"])


def downgrade() -> None:
    op.drop_index("idx_decision_records_action", table_name="decision_records")
    op.drop_index("idx_decision_records_user_time", table_name="decision_records")
    op.drop_table("decision_records")
