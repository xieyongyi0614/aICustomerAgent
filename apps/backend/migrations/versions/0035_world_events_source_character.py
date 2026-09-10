"""world_events.source 放宽为允许 'character'（角色动作事件历史）。

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-10

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_world_events_source", "world_events", type_="check")
    op.create_check_constraint(
        "ck_world_events_source",
        "world_events",
        "source IN ('user_mention', 'manual', 'autonomy', 'character')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_world_events_source", "world_events", type_="check")
    op.create_check_constraint(
        "ck_world_events_source",
        "world_events",
        "source IN ('user_mention', 'manual', 'autonomy')",
    )
