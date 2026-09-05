"""V2.0.0 MEM 类型体系收口：memories.type 扩展为 7 规范 + 2 遗留类型。

7 类规范类型（design.md §3）：user_preference / user_fact / experience /
relationship_fact / commitment / milestone_event / behavior_pattern；
2 类 v1 遗留（important_event / relationship_event）保持合法以兼容既有行。
v2 转正入口（memory2/evaluator）统一归一化为规范类型，v1 路径行为不变。

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WIDENED_CHECK = (
    "type IN ('user_preference', 'user_fact', 'important_event',"
    " 'relationship_event', 'experience', 'relationship_fact',"
    " 'commitment', 'milestone_event', 'behavior_pattern')"
)
LEGACY_CHECK = (
    "type IN ('user_preference', 'user_fact', 'important_event', 'relationship_event')"
)


def _rebuild_check(target_check: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_memories_type", "memories", type_="check")
        op.create_check_constraint("ck_memories_type", "memories", target_check)
    else:
        with op.batch_alter_table("memories") as batch:
            batch.drop_constraint("ck_memories_type", type_="check")
            batch.create_check_constraint("ck_memories_type", target_check)


def upgrade() -> None:
    _rebuild_check(WIDENED_CHECK)


def downgrade() -> None:
    _rebuild_check(LEGACY_CHECK)
