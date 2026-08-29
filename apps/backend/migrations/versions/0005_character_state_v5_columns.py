"""character_state v5 columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("character_state") as batch:
        batch.add_column(
            sa.Column("intensity", sa.Float(), nullable=False, server_default="0.3")
        )
        batch.add_column(
            sa.Column("cause", sa.String(), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("last_event_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("character_state") as batch:
        batch.drop_column("last_event_at")
        batch.drop_column("cause")
        batch.drop_column("intensity")
