"""llm_call_records 表（V7.8-003，风格对齐 0012）。

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-30

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_call_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_id", sa.String(), nullable=True),
        sa.Column("turn_id", sa.String(), nullable=True),
        sa.Column("call_site", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ttft_ms", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_estimate", sa.Float(), nullable=True),
        sa.Column("error_kind", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('ok', 'error')",
            name="ck_llm_call_records_status",
        ),
    )
    op.create_index("idx_llm_calls_request", "llm_call_records", ["request_id"])
    op.create_index("idx_llm_calls_turn", "llm_call_records", ["turn_id"])
    op.create_index("idx_llm_calls_time", "llm_call_records", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_llm_calls_time", table_name="llm_call_records")
    op.drop_index("idx_llm_calls_turn", table_name="llm_call_records")
    op.drop_index("idx_llm_calls_request", table_name="llm_call_records")
    op.drop_table("llm_call_records")
