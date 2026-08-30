"""world 四表（V8-002，风格对齐 0016）。

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worlds",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False, server_default="home"),
        sa.Column("time_mode", sa.String(), nullable=False, server_default="real_sync"),
        sa.Column("sim_time", sa.DateTime(), nullable=True),
        sa.Column("sim_rate", sa.Float(), nullable=False, server_default="1"),
        sa.Column("current_location", sa.String(), nullable=False),
        sa.Column("environment", sa.JSON(), nullable=False),
        sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_worlds_user"),
        sa.CheckConstraint(
            "time_mode IN ('real_sync', 'simulated', 'story')",
            name="ck_worlds_time_mode",
        ),
    )
    op.create_table(
        "world_entities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("world_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("location_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("properties", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("last_action_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN ('food', 'drink', 'tool', 'furniture', 'clothing', 'device', 'misc')",
            name="ck_world_entities_category",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'destroyed')",
            name="ck_world_entities_status",
        ),
    )
    op.create_index(
        "idx_world_entities_world_location",
        "world_entities",
        ["world_id", "location_id"],
    )
    op.create_index(
        "idx_world_entities_world_status",
        "world_entities",
        ["world_id", "status"],
    )
    op.create_table(
        "world_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("world_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("importance", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="user_mention"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "importance IN ('low', 'normal', 'high')",
            name="ck_world_events_importance",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'active', 'completed', 'cancelled', 'expired')",
            name="ck_world_events_status",
        ),
        sa.CheckConstraint(
            "source IN ('user_mention', 'manual', 'autonomy')",
            name="ck_world_events_source",
        ),
    )
    op.create_index(
        "idx_world_events_world_due",
        "world_events",
        ["world_id", "status", "due_at"],
    )
    op.create_table(
        "world_snapshots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("world_id", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_world_snapshots_world_time",
        "world_snapshots",
        ["world_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_world_snapshots_world_time", table_name="world_snapshots")
    op.drop_table("world_snapshots")
    op.drop_index("idx_world_events_world_due", table_name="world_events")
    op.drop_table("world_events")
    op.drop_index("idx_world_entities_world_status", table_name="world_entities")
    op.drop_index("idx_world_entities_world_location", table_name="world_entities")
    op.drop_table("world_entities")
    op.drop_table("worlds")
