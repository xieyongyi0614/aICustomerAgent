"""默认用户概念退役：users.is_default 列与唯一索引删除。

Revision ID: 0058
Revises: 0057
Create Date: 2026-09-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ux_users_is_default", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("is_default")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column(
                "is_default", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    op.create_index(
        "ux_users_is_default",
        "users",
        ["is_default"],
        unique=True,
        sqlite_where=sa.text("is_default"),
        postgresql_where=sa.text("is_default"),
    )
