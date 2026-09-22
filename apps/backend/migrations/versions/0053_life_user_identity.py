"""PLA-001 用户实体：users 表 + 默认用户唯一部分索引。

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_users_status",
        ),
    )
    op.create_index(
        "ux_users_is_default",
        "users",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default"),
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    try:
        op.drop_index("ux_users_is_default", table_name="users")
    except Exception:
        pass
    op.drop_table("users")
