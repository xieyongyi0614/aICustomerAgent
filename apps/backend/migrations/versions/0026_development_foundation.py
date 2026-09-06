"""V2.0.0 DEV-001：Development 存储基座。

新增 development_state / development_changes 两张表。development_state 承载
Belief/Preference/Pattern 调制（status/kind CheckConstraint + strength 0~1 约束）；
development_changes 记录 before/after 审计（insight_id 必填，可溯 insights 行，
insights 为审计表不物理删除故不建外键）。同 (user_id, key) 至多一条 active 由
部分唯一索引兜底（服务层条件 UPDATE 为第一保证）。

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "development_state",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False, server_default="asuna"),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("source_insight_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'retired')",
            name="ck_development_state_status",
        ),
        sa.CheckConstraint(
            "kind IN ('belief', 'preference', 'pattern')",
            name="ck_development_state_kind",
        ),
        sa.CheckConstraint(
            "strength >= 0 AND strength <= 1",
            name="ck_development_state_strength",
        ),
    )
    op.create_index(
        "idx_development_state_user_status", "development_state", ["user_id", "status"]
    )
    op.create_index(
        "idx_development_state_user_kind", "development_state", ["user_id", "kind", "status"]
    )
    op.create_index(
        "uq_development_state_active_key",
        "development_state",
        ["user_id", "key"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "development_changes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("development_state_id", sa.String(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column("insight_id", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False, server_default="compiled"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "reason IN ('compiled', 'arbitrated', 'arbitrated_lost',"
            " 'rolled_back', 'retired', 'replayed')",
            name="ck_development_changes_reason",
        ),
    )
    op.create_index(
        "idx_development_changes_state", "development_changes", ["development_state_id"]
    )
    op.create_index(
        "idx_development_changes_insight", "development_changes", ["insight_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_development_changes_insight", table_name="development_changes")
    op.drop_index("idx_development_changes_state", table_name="development_changes")
    op.drop_table("development_changes")
    op.drop_index("uq_development_state_active_key", table_name="development_state")
    op.drop_index("idx_development_state_user_kind", table_name="development_state")
    op.drop_index("idx_development_state_user_status", table_name="development_state")
    op.drop_table("development_state")
