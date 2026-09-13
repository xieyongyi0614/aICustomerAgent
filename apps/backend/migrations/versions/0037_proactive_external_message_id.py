"""proactive_actions 增加 external_message_id 列（AUTO-005 投递链路闭合）。

message_id 保持内部 messages 行 id 语义；external_message_id 存 Channel
侧消息 id（SendResult.external_message_id），nullable 可回退。

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "proactive_actions",
        sa.Column("external_message_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("proactive_actions", "external_message_id")
