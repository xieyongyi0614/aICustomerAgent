"""conversations 表新增 mode / mode_entered_at（persistence.md §2）。

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column(
                "mode",
                sa.String(16),
                nullable=False,
                server_default="default",
                comment="会话模式：professional | default | immersive（迟滞确认值）",
            )
        )
        batch.add_column(
            sa.Column(
                "mode_entered_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="当前 mode 进入时间（R4 空闲回落计算用；存量行 NULL 视作 now）",
            )
        )
        batch.create_check_constraint(
            "ck_conversations_mode",
            "mode IN ('professional', 'default', 'immersive')",
        )


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("ck_conversations_mode", type_="check")
        batch.drop_column("mode_entered_at")
        batch.drop_column("mode")
