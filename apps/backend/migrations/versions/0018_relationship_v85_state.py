"""V8.5 关系域扩列：relationship_state 6 维 + events 扩列扩值（V8.5-001）。

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENT_TYPE_VALUES_V85 = (
    "user_care",
    "user_help",
    "intimate_moment",
    "long_interaction",
    "praise",
    "warm_moment",
    "criticized",
    "conflict",
    "boundary_violation",
    "promise_kept",
    "promise_broken",
    "none",
)

EVENT_SOURCE_VALUES_V85 = ("conversation", "memory_replay", "system")


def upgrade() -> None:
    with op.batch_alter_table("relationship_state") as batch:
        batch.add_column(
            sa.Column("respect", sa.Float(), nullable=False, server_default="0.6")
        )
        batch.add_column(
            sa.Column("comfort", sa.Float(), nullable=False, server_default="0.6")
        )
        batch.add_column(
            sa.Column(
                "conflict_status", sa.String(), nullable=False, server_default="none"
            )
        )
        batch.add_column(
            sa.Column(
                "neglect_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("last_interaction_at", sa.DateTime(), nullable=True)
        )
        batch.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint(
            "ck_relationship_state_conflict_status",
            "conflict_status IN ('none', 'strain', 'conflict', 'cold', 'recovery',"
            " 'resolved')",
        )

    with op.batch_alter_table("relationship_events") as batch:
        batch.add_column(
            sa.Column(
                "impact_respect", sa.Float(), nullable=False, server_default="0"
            )
        )
        batch.add_column(
            sa.Column(
                "impact_comfort", sa.Float(), nullable=False, server_default="0"
            )
        )
        batch.drop_constraint("ck_relationship_events_type", type_="check")
        batch.create_check_constraint(
            "ck_relationship_events_type",
            "type IN (" + ", ".join(f"'{value}'" for value in EVENT_TYPE_VALUES_V85) + ")",
        )
        batch.create_check_constraint(
            "ck_relationship_events_source",
            "source IN ("
            + ", ".join(f"'{value}'" for value in EVENT_SOURCE_VALUES_V85)
            + ")",
        )


def downgrade() -> None:
    with op.batch_alter_table("relationship_events") as batch:
        batch.drop_constraint("ck_relationship_events_source", type_="check")
        batch.drop_constraint("ck_relationship_events_type", type_="check")
        batch.create_check_constraint(
            "ck_relationship_events_type",
            "type IN ('user_care', 'user_help', 'intimate_moment', 'long_interaction',"
            " 'praise', 'criticized', 'conflict', 'boundary_violation', 'none')",
        )
        batch.drop_column("impact_comfort")
        batch.drop_column("impact_respect")

    with op.batch_alter_table("relationship_state") as batch:
        batch.drop_constraint(
            "ck_relationship_state_conflict_status", type_="check"
        )
        batch.drop_column("version")
        batch.drop_column("last_interaction_at")
        batch.drop_column("neglect_active")
        batch.drop_column("conflict_status")
        batch.drop_column("comfort")
        batch.drop_column("respect")
