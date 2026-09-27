"""邮箱验证码登录：users.email 唯一绑定。

Revision ID: 0057
Revises: 0056
Create Date: 2026-09-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=320), nullable=True))
    op.create_index(
        "ux_users_email",
        "users",
        ["email"],
        unique=True,
        sqlite_where=sa.text("email IS NOT NULL"),
        postgresql_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_users_email", table_name="users")
    op.drop_column("users", "email")
