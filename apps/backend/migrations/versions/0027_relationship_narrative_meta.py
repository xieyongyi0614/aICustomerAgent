"""V2.0.0 REL-004：relationship_milestones 叙事里程碑溯源位。

新增 nullable meta JSON 列（NULL 默认）：数值里程碑行零影响（meta=NULL），
账本语义不变；叙事里程碑行经 meta 记录 source=insight / insight_id /
matched_rule（E-REL-04 可溯源 Insight）。

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("relationship_milestones", sa.Column("meta", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("relationship_milestones", "meta")
