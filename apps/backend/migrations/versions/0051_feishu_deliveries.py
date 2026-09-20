"""飞书出站投递幂等表（FEISHU-011，多实例硬前置之一）。

`delivery._delivered` 是进程内表：多 worker / 多实例下同一逻辑消息会被每个实例各投
一次（重复回复用户）。本表把出站幂等落到持久化存储，用主键唯一约束做原子占位：

    INSERT INTO feishu_deliveries (idempotency_key, delivered_at) VALUES (?, ?)
    ON CONFLICT (idempotency_key) DO NOTHING   -- rowcount == 1 即占位成功

幂等键由 `delivery` 生成，形如 `reply:{message_id}:{段号}` 与
`proactive:{channel}:{收件人}:{业务键}:{段号}`。

`delivered_at` 供 TTL 清理（`purge_before`），并为该列建索引避免全表扫描。

Revision ID: 0051
Revises: 0050
Create Date: 2026-09-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feishu_deliveries",
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("idempotency_key", name="pk_feishu_deliveries"),
    )
    op.create_index(
        "idx_feishu_deliveries_delivered_at",
        "feishu_deliveries",
        ["delivered_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_feishu_deliveries_delivered_at", table_name="feishu_deliveries")
    op.drop_table("feishu_deliveries")
