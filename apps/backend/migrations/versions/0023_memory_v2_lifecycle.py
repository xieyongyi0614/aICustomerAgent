"""V2.0.0 MEM-005：Memory 2.0 生命周期列。

memories 扩列 forgotten_at（显式遗忘/自动遗忘的软删时间戳，30 天保留期后物理删）
与 last_decayed_at（衰减日桶游标，按日幂等）。全部可 NULL，v1 代码不可见。

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("forgotten_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "memories",
        sa.Column("last_decayed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memories", "last_decayed_at")
    op.drop_column("memories", "forgotten_at")
