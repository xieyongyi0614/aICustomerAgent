"""0010：V6.0.0 记忆域合并迁移（类型词表收窄 + 事件源收窄 + `memories.layer`）。

> **合并说明（用户裁决 2026-10-16）**：同属 V6.0.0 且**尚未在任何环境应用**的迁移不再逐域拆分
> ——原 `0010`（词表收窄）、原 `0011`（事件源收窄）与 `MEV-005` 的加列合并为**单条**迁移；
> 库可重建，重写未发布迁移不留历史负担。

承载三项，顺序不可换（先收窄值域，再按归一的类型回填层）：

1. **`memories.type` 遗留值退役**（`MEV-015`）：存量遗留行就地归一
   （`important_event → experience`、`relationship_event → relationship_fact`，与
   `services/memory/types.py::LEGACY_TYPE_ALIASES` 同映射），随后 `ck_memories_type`
   收窄为 7 规范值；
2. **`relationship_events.source` 收窄**（回放补记退役清账）：删除派生行（`source='memory_replay'`），
   随后 `ck_relationship_events_source` 收窄为 `conversation` / `system`；
3. **`memories.layer` 列**（`MEV-005`）：加列（`server_default='semantic'` 兜存量行，避免 NULL 窗口）
   → 幂等回填（`experience` / `milestone_event` → `episodic`，带 `layer <> 'episodic'` 守卫）
   → 撤 `server_default`（此后漏设 `layer` 的写入显式失败，fail-closed）→ CHECK → 索引。

降级逆序执行（删索引 → 删 CHECK/列 → 放宽事件源值域 → 放宽类型值域）；**数据侧不反向还原**
（类型归一与派生行删除均不可逆）。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"

MEMORIES_TABLE = "memories"
MEMORIES_TYPE_CONSTRAINT = "ck_memories_type"
LAYER_COLUMN = "layer"
LAYER_TYPE_LENGTH = 16
LAYER_CONSTRAINT = "ck_memories_layer"
LAYER_INDEX = "idx_memories_user_layer_status"

RELATIONSHIP_TABLE = "relationship_events"
RELATIONSHIP_SOURCE_CONSTRAINT = "ck_relationship_events_source"

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

MEMORY_LAYERS: tuple[str, ...] = ("episodic", "semantic")
"""与 `app/core/constants.py::MEMORY_LAYERS` 同源（迁移内自持，避免依赖应用层）。"""

DEFAULT_LAYER = "semantic"

EPISODIC_TYPES: tuple[str, ...] = ("experience", "milestone_event")
"""回填为 `episodic` 的类型（其余保持基座 `semantic`）；含遗留名以兼容单独重跑回填的场景。"""

# 回填 SQL（幂等：带 `<> 'episodic'` 守卫，重复执行结果不变）
BACKFILL_LAYERS_SQL = (
    f"UPDATE {MEMORIES_TABLE} SET {LAYER_COLUMN} = 'episodic' "
    f"WHERE type IN {(*EPISODIC_TYPES, 'important_event')} "
    f"AND {LAYER_COLUMN} <> 'episodic'"
)

RETAINED_SOURCES: tuple[str, ...] = ("conversation", "system")
RETIRED_SOURCE = "memory_replay"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _replace_check(table: str, name: str, clause: str) -> None:
    """替换 CHECK：PG 走 DROP + ADD；SQLite 走 batch 重建表。"""
    if _is_sqlite():
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, clause)
        return
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, clause, table)


def _memory_type_clause(types: tuple[str, ...]) -> str:
    return "type IN (" + ", ".join(f"'{value}'" for value in types) + ")"


def _layer_clause() -> str:
    # 必须传**完整布尔式**（仓库已知陷阱：传值清单会在 PG 上 DatatypeMismatch）
    return f"{LAYER_COLUMN} IN {MEMORY_LAYERS}"


def _source_clause(sources: tuple[str, ...]) -> str:
    return "source IN (" + ", ".join(f"'{value}'" for value in sources) + ")"


def _normalize_legacy_memory_types() -> None:
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        op.execute(
            f"UPDATE {MEMORIES_TABLE} SET type = '{canonical}' WHERE type = '{legacy}'"
        )


def _delete_replay_relationship_rows() -> None:
    op.execute(
        f"DELETE FROM {RELATIONSHIP_TABLE} WHERE source = '{RETIRED_SOURCE}'"
    )


def _add_layer_column() -> None:
    op.add_column(
        MEMORIES_TABLE,
        sa.Column(
            LAYER_COLUMN,
            sa.String(length=LAYER_TYPE_LENGTH),
            nullable=False,
            server_default=DEFAULT_LAYER,
        ),
    )


def _finalize_layer_column() -> None:
    """撤 `server_default` + 建 CHECK（SQLite 合并进同一个 batch 重建）。"""
    if _is_sqlite():
        with op.batch_alter_table(MEMORIES_TABLE, recreate="always") as batch:
            batch.alter_column(LAYER_COLUMN, server_default=None)
            batch.create_check_constraint(LAYER_CONSTRAINT, _layer_clause())
        return
    op.alter_column(MEMORIES_TABLE, LAYER_COLUMN, server_default=None)
    op.create_check_constraint(LAYER_CONSTRAINT, _layer_clause(), MEMORIES_TABLE)


def _drop_layer_column() -> None:
    if _is_sqlite():
        with op.batch_alter_table(MEMORIES_TABLE, recreate="always") as batch:
            batch.drop_constraint(LAYER_CONSTRAINT, type_="check")
            batch.drop_column(LAYER_COLUMN)
        return
    op.drop_constraint(LAYER_CONSTRAINT, MEMORIES_TABLE, type_="check")
    op.drop_column(MEMORIES_TABLE, LAYER_COLUMN)


def upgrade() -> None:
    """① 类型词表收窄 → ② 事件源收窄 → ③ `layer` 列 + 回填 + CHECK + 索引。"""
    _normalize_legacy_memory_types()
    _replace_check(
        MEMORIES_TABLE, MEMORIES_TYPE_CONSTRAINT, _memory_type_clause(CANONICAL_TYPES)
    )

    _delete_replay_relationship_rows()
    _replace_check(
        RELATIONSHIP_TABLE,
        RELATIONSHIP_SOURCE_CONSTRAINT,
        _source_clause(RETAINED_SOURCES),
    )

    _add_layer_column()
    op.execute(BACKFILL_LAYERS_SQL)
    _finalize_layer_column()
    op.create_index(
        LAYER_INDEX, MEMORIES_TABLE, ["user_id", LAYER_COLUMN, "status"]
    )


def downgrade() -> None:
    """逆序回退结构；值域放宽但数据不还原。"""
    op.drop_index(LAYER_INDEX, table_name=MEMORIES_TABLE)
    _drop_layer_column()

    _replace_check(
        RELATIONSHIP_TABLE,
        RELATIONSHIP_SOURCE_CONSTRAINT,
        _source_clause((*RETAINED_SOURCES, RETIRED_SOURCE)),
    )
    _replace_check(
        MEMORIES_TABLE,
        MEMORIES_TYPE_CONSTRAINT,
        _memory_type_clause(CANONICAL_TYPES + LEGACY_TYPES),
    )
