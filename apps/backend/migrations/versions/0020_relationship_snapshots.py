"""V8.5 relationship_snapshots 表：关键帧快照（V8.5-007）。

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "relationship_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("stage", sa.String(), nullable=False),
        sa.Column("conflict_status", sa.String(), nullable=False, server_default="none"),
        sa.Column("trigger", sa.String(), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "stage IN ('stranger', 'friend', 'close_friend', 'partner')",
            name="ck_relationship_snapshots_stage",
        ),
        sa.CheckConstraint(
            "conflict_status IN ('none', 'strain', 'conflict', 'cold', 'recovery', 'resolved')",
            name="ck_relationship_snapshots_conflict_status",
        ),
    )
    op.create_index(
        "idx_relationship_snapshots_user_version",
        "relationship_snapshots",
        ["user_id", "version"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_relationship_snapshots_user_version", table_name="relationship_snapshots"
    )
    op.drop_table("relationship_snapshots")
