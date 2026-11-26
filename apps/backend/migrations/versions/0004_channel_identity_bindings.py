"""0004：channel_identities 成为全通道统一凭据绑定表。

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03

ADR-16（ID 体系改用雪花 ID）配套：
- `internal_user_id` 语义由「`{channel}:{external_id}` 派生串」正名为**真实 `users.id`**；
- `session_id` 改为可空——仅飞书等有「默认会话」语义的通道写入，
  邮箱绑定行（`channel='email'`）无会话概念。

用 `batch_alter_table` 以兼容 SQLite（其不支持 `ALTER COLUMN ... DROP NOT NULL`，
批处理模式下改为重建表）。列类型与数据由 B2 步（列类型翻转）承担，本迁移只放开 NULL 约束。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("channel_identities") as batch_op:
        batch_op.alter_column(
            "session_id",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("channel_identities") as batch_op:
        batch_op.alter_column(
            "session_id",
            existing_type=sa.String(),
            nullable=False,
        )
