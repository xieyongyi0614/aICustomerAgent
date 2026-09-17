"""V2.6.1 REF-104b：action_records.run_id 独立列（D10 溯源与 session_id 解耦）。

Revision ID: 0048
Revises: 0047
Create Date: 2026-09-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "action_records",
        sa.Column("run_id", sa.String(), nullable=True),
    )
    try:
        op.create_index(
            "ix_action_records_run_id",
            "action_records",
            ["run_id"],
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_index("ix_action_records_run_id", table_name="action_records")
    except Exception:
        pass
    op.drop_column("action_records", "run_id")
