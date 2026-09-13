"""decision_records 扩列 candidates（AGENT-004）：候选清单/来源/六维得分审计。

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-13

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("decision_records", sa.Column("candidates", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("decision_records", "candidates")
