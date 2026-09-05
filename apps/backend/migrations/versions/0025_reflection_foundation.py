"""V2.0.0 REF-001：Reflection 存储基座。

新增 insights / reflection_runs / evidence_links 三张表。insights 承载反思产物
（status/type/scope CheckConstraint + invalidated_reason 必填约束）；reflection_runs
记录反思任务运行（queued→running→done|skipped|failed）；evidence_links 为
insight→memory 引用（不建外键，memories 物理删除后由读取侧过滤悬空链接）。

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "insights",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_reason", sa.Text(), nullable=True),
        sa.Column("superseded_by", sa.String(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'invalidated')",
            name="ck_insights_status",
        ),
        sa.CheckConstraint(
            "type IN ('belief', 'preference', 'pattern')",
            name="ck_insights_type",
        ),
        sa.CheckConstraint(
            "scope IN ('user', 'relationship', 'world')",
            name="ck_insights_scope",
        ),
        sa.CheckConstraint(
            "status != 'invalidated' OR invalidated_reason IS NOT NULL",
            name="ck_insights_invalidated_reason",
        ),
    )
    op.create_index("idx_insights_user_status", "insights", ["user_id", "status"])
    op.create_index(
        "idx_insights_user_scope_status", "insights", ["user_id", "scope", "status"]
    )

    op.create_table(
        "reflection_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("evidence_summary", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("llm_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("insight_ids", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'skipped', 'failed')",
            name="ck_reflection_runs_status",
        ),
        sa.CheckConstraint(
            "trigger IN ('scheduled', 'event')",
            name="ck_reflection_runs_trigger",
        ),
    )
    op.create_index("idx_reflection_runs_user_status", "reflection_runs", ["user_id", "status"])
    op.create_index(
        "idx_reflection_runs_status_created", "reflection_runs", ["status", "created_at"]
    )

    op.create_table(
        "evidence_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("insight_id", sa.String(), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("insight_id", "memory_id", name="uq_evidence_links_insight_memory"),
    )
    op.create_index("idx_evidence_links_memory", "evidence_links", ["memory_id"])


def downgrade() -> None:
    op.drop_index("idx_evidence_links_memory", table_name="evidence_links")
    op.drop_table("evidence_links")
    op.drop_index("idx_reflection_runs_status_created", table_name="reflection_runs")
    op.drop_index("idx_reflection_runs_user_status", table_name="reflection_runs")
    op.drop_table("reflection_runs")
    op.drop_index("idx_insights_user_scope_status", table_name="insights")
    op.drop_index("idx_insights_user_status", table_name="insights")
    op.drop_table("insights")
