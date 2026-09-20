"""飞书入站事件去重表（FEISHU-010，多实例硬前置之一）。

进程内去重表（`events._seen_events`）在多 worker / 多实例下无法共享：同一
`event_id` 会被每个实例各受理一次，导致重复 LLM 调用与重复回复。本表把去重
落到**有 WAL 持久化**的存储上，用主键唯一约束做原子判定：

    INSERT INTO feishu_dedupe_ledger (event_id, received_at) VALUES (?, ?)
    ON CONFLICT (event_id) DO NOTHING      -- rowcount == 1 即首次受理

`received_at` 供 TTL 清理（`purge_before`），并为该列建索引避免全表扫描。

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-20

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feishu_dedupe_ledger",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_feishu_dedupe_ledger"),
    )
    op.create_index(
        "idx_feishu_dedupe_ledger_received_at", "feishu_dedupe_ledger", ["received_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_feishu_dedupe_ledger_received_at", table_name="feishu_dedupe_ledger")
    op.drop_table("feishu_dedupe_ledger")
