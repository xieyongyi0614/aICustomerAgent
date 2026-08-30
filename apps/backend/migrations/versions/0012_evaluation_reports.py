"""evaluation_reports 表（V7.5-002，风格对齐 0011）。

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evaluation_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "character_id", sa.String(), nullable=False, server_default="asuna"
        ),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("context_digest", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "subject IN ('turn', 'proactive_action', 'offline_batch')",
            name="ck_evaluation_reports_subject",
        ),
        sa.CheckConstraint(
            "verdict IN ('pass', 'warn', 'fail')",
            name="ck_evaluation_reports_verdict",
        ),
    )
    op.create_index(
        "idx_evaluation_user_time",
        "evaluation_reports",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_evaluation_subject",
        "evaluation_reports",
        ["subject", "subject_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_evaluation_subject", table_name="evaluation_reports")
    op.drop_index("idx_evaluation_user_time", table_name="evaluation_reports")
    op.drop_table("evaluation_reports")
