"""0011：`relationship_events.source` 枚举收窄（`memory_replay` 退役）。

背景：`memory_replay` 是「记忆回放补记」写回账本的派生行来源。该功能已于 2026-10-16
随遗留记忆类型退役整体删除（`conversation/state.py::_replay_relationship_memories` 及其
settings 一并移除），故账本不再有任何写入方产出该值；枚举与 CHECK 收窄为
`conversation` / `system` 两值。

本迁移两步：
1. 删除存量派生行（`source='memory_replay'`）——它们是「记忆 → 账本」的派生物，
   记忆侧遗留类型已不可存储，派生行随之失去语义；库将重建时本步为 no-op；
2. `ck_relationship_events_source` 收窄为两值（PG：DROP + ADD；SQLite：batch 重建表）。

降级只放宽值域（回三值），不反向还原已删除的派生行（不可逆，且已无数值真相价值）。
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"

TABLE = "relationship_events"
CONSTRAINT = "ck_relationship_events_source"

RETAINED_SOURCES: tuple[str, ...] = ("conversation", "system")

RETIRED_SOURCE = "memory_replay"


def _check_clause(sources: tuple[str, ...]) -> str:
    return "source IN (" + ", ".join(f"'{value}'" for value in sources) + ")"


def _replace_check(sources: tuple[str, ...]) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_constraint(CONSTRAINT, type_="check")
            batch.create_check_constraint(CONSTRAINT, _check_clause(sources))
        return
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, _check_clause(sources), TABLE)


def upgrade() -> None:
    """删除派生行 → CHECK 收窄为两值。"""
    op.execute(f"DELETE FROM {TABLE} WHERE source = '{RETIRED_SOURCE}'")
    _replace_check(RETAINED_SOURCES)


def downgrade() -> None:
    """只放宽值域（回三值）；已删除的派生行不还原。"""
    _replace_check((*RETAINED_SOURCES, RETIRED_SOURCE))
