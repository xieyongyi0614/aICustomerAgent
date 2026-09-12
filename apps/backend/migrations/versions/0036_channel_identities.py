"""channel_identities 表（FEISHU-003）：复合主键 (channel, external_id) + 反查索引。

新表 create_table 在两方言通用，无需 batch_alter_table（0035 的注意事项只作用于 ALTER CONSTRAINT）。

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_identities",
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("internal_user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("external_union_id", sa.String(), nullable=True),
        sa.Column("external_tenant_key", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("channel", "external_id"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_channel_identities_status",
        ),
    )
    op.create_index(
        "idx_channel_identities_user",
        "channel_identities",
        ["internal_user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_channel_identities_user", table_name="channel_identities")
    op.drop_table("channel_identities")
