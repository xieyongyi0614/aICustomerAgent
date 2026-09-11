"""world_events.source 放宽为允许 'character'（角色动作事件历史）。

注意：SQLite 方言不支持 ALTER CONSTRAINT，故非 PostgreSQL 走 batch_alter_table
（copy-and-move 策略），保证单测在 SQLite 上跑迁移链也可往返（沿 0024 模式）。

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

TARGET_CHECK = (
    "source IN ('user_mention', 'manual', 'autonomy', 'character')"
)
LEGACY_CHECK = "source IN ('user_mention', 'manual', 'autonomy')"


def _rebuild_check(target_check: str) -> None:
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
    _rebuild_check(TARGET_CHECK)


def downgrade() -> None:
    _rebuild_check(LEGACY_CHECK)
