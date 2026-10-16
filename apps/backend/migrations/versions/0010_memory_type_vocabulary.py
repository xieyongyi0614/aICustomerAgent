"""0010：记忆类型词表收窄为 7 规范值（遗留类型退役）。

背景：`memories.type` 的 `ck_memories_type` 一直放行 9 值（7 规范 + 2 遗留
`important_event` / `relationship_event`）。2026-10-16 起遗留类型**退役**：存储词表 = 7 规范值，
遗留名只保留在**入站归一**（`services/memory/types.py::LEGACY_TYPE_ALIASES`）。

本迁移两步，均可重跑：
1. 存量遗留行就地归一（`important_event → experience`、`relationship_event → relationship_fact`，
   与 `LEGACY_TYPE_ALIASES` 同映射）——库将重建时本步为 no-op；
2. `ck_memories_type` 收窄为 7 值（PG：DROP + ADD；SQLite：batch 重建表）。

范围：只动 `memories.type` 与该 CHECK。`memory_candidates.proposed_type` 无 CHECK
（入口归一由 `services/memory/ingest.create_candidate` 承担）。降级只放宽值域，
不反向还原已归一的存量行（归一不可逆，且旧名已无写入方）。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"

TABLE = "memories"
CONSTRAINT = "ck_memories_type"

CANONICAL_TYPES: tuple[str, ...] = (
    "user_preference",
    "user_fact",
    "experience",
    "relationship_fact",
    "commitment",
    "milestone_event",
    "behavior_pattern",
)

LEGACY_TYPES: tuple[str, ...] = ("important_event", "relationship_event")

LEGACY_TO_CANONICAL: dict[str, str] = {
    "important_event": "experience",
    "relationship_event": "relationship_fact",
}


def _check_clause(types: tuple[str, ...]) -> str:
    return "type IN (" + ", ".join(f"'{value}'" for value in types) + ")"


def _normalize_legacy_rows() -> None:
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        op.execute(f"UPDATE {TABLE} SET type = '{canonical}' WHERE type = '{legacy}'")


def _replace_check(types: tuple[str, ...]) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_constraint(CONSTRAINT, type_="check")
            batch.create_check_constraint(CONSTRAINT, _check_clause(types))
        return
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, _check_clause(types), TABLE)


def upgrade() -> None:
    """遗留行归一 → CHECK 收窄为 7 规范值。"""
    _normalize_legacy_rows()
    _replace_check(CANONICAL_TYPES)


def downgrade() -> None:
    """只放宽值域（9 值）；不反向还原已归一的存量行。"""
    _replace_check(CANONICAL_TYPES + LEGACY_TYPES)
