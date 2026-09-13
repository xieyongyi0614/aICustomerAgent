"""WS-002 V2.3.0 世界模拟扩列：worlds.sim_last_advanced_at / world_events.idempotency_key
与 source 词表放宽（time/weather/calendar/user_evidence/daily_life/simulation）。

SQLite 方言不支持 ALTER CONSTRAINT，走 batch_alter_table copy-and-move（沿 0035 模式）。

Revision ID: 0045
Revises: 0044
Create Date: 2026-09-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_SOURCES = "('user_mention', 'manual', 'autonomy', 'character')"
TARGET_SOURCES = (
    "('user_mention', 'manual', 'autonomy', 'character', "
    "'time', 'weather', 'calendar', 'user_evidence', 'daily_life', 'simulation')"
)


def _rebuild_source_check(target_check: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_world_events_source", "world_events", type_="check")
        op.create_check_constraint(
            "ck_world_events_source", "world_events", target_check
        )
    else:
        with op.batch_alter_table("world_events") as batch:
            batch.drop_constraint("ck_world_events_source", type_="check")
            batch.create_check_constraint("ck_world_events_source", target_check)


def upgrade() -> None:
    op.add_column(
        "worlds",
        sa.Column("sim_last_advanced_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "world_events",
        sa.Column("idempotency_key", sa.String(100), nullable=True),
    )
    op.create_index(
        "uq_world_events_idempotency",
        "world_events",
        ["idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    _rebuild_source_check(TARGET_SOURCES)


def downgrade() -> None:
    _rebuild_source_check(LEGACY_SOURCES)
    op.drop_index("uq_world_events_idempotency", table_name="world_events")
    op.drop_column("world_events", "idempotency_key")
    op.drop_column("worlds", "sim_last_advanced_at")
