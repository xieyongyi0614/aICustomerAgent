"""world_entities 增加 unit 与 consumable 列（Household Inventory）。

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "world_entities",
        sa.Column("unit", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "world_entities",
        sa.Column("consumable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("world_entities", "consumable")
    op.drop_column("world_entities", "unit")