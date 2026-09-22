"""WS-002 V2.3.0 世界模拟扩列：worlds.sim_last_advanced_at / world_events.idempotency_key
与 source 词表放宽（time/weather/calendar/user_evidence/daily_life/simulation）。

约束放宽（ck_world_events_source）无法用 ALTER 完成，两方言处理方式不同：
- PostgreSQL：DROP CONSTRAINT + CREATE CHECK（原生支持）。
- SQLite：表级重建。此处**不走 batch_alter_table**——batch 模式会反射既有具名
  CHECK/索引并在临时表上重建，其 INSERT ... SELECT 在 SQLite 上会触发
  "row value misused"（实测 0044→0045 干净升级链必现）。改为手写
  rename → create → copy → drop 序列，DDL 完全可控。

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

_ADDED_COLUMN = "idempotency_key"

_WORLD_EVENTS_COLUMNS = (
    ("id", "VARCHAR NOT NULL"),
    ("world_id", "VARCHAR NOT NULL"),
    ("type", "VARCHAR NOT NULL"),
    ("title", "VARCHAR NOT NULL"),
    ("importance", "VARCHAR NOT NULL"),
    ("status", "VARCHAR NOT NULL"),
    ("started_at", "DATETIME"),
    ("due_at", "DATETIME"),
    ("completed_at", "DATETIME"),
    ("payload", "JSON NOT NULL"),
    ("source", "VARCHAR NOT NULL DEFAULT 'user_mention'"),
    ("created_at", "DATETIME NOT NULL"),
    ("updated_at", "DATETIME NOT NULL"),
)

_CARRY_OVER_INDEXES = (
    ("idx_world_events_world_due", "world_id, status, due_at", False),
)


def _rebuild_source_check(target_check: str, *, with_idempotency_key: bool) -> None:
    """放宽 world_events.source 值域 CHECK。

    `target_check` 是**值清单**（形如 `('a', 'b')`），不是完整布尔表达式：
    两方言各自包一层 `source IN (...)`——直接当表达式传给 PostgreSQL 会被判为
    record 而非 boolean（`DatatypeMismatch: argument of CHECK must be type boolean`）。

    with_idempotency_key 表示目标表是否包含 idempotency_key 列
    （升级 True / 降级 False），建表与数据搬运按此对齐。
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_world_events_source", "world_events", type_="check")
        op.create_check_constraint(
            "ck_world_events_source", "world_events", f"source IN {target_check}"
        )
        return
    _sqlite_rebuild_world_events(
        target_check, with_idempotency_key=with_idempotency_key
    )


def _sqlite_rebuild_world_events(
    source_check: str, *, with_idempotency_key: bool
) -> None:
    """SQLite：手写表重建，替代 batch_alter_table（规避 row value misused）。"""
    bind = op.get_bind()
    target_columns = list(_WORLD_EVENTS_COLUMNS)
    if with_idempotency_key:
        target_columns.insert(13, (_ADDED_COLUMN, "VARCHAR(100)"))

    column_ddl = ", ".join(f"{name} {ddl}" for name, ddl in target_columns)
    create_table = (
        f"CREATE TABLE world_events_new ({column_ddl}, "
        f"PRIMARY KEY (id), "
        f"CONSTRAINT ck_world_events_importance "
        f"CHECK (importance IN ('low', 'normal', 'high')), "
        f"CONSTRAINT ck_world_events_status "
        f"CHECK (status IN ('scheduled', 'active', 'completed', 'cancelled', 'expired')), "
        f"CONSTRAINT ck_world_events_source CHECK (source IN {source_check}))"
    )
    target_names = ", ".join(name for name, _ in target_columns)
    select_exprs = ", ".join(
        name if name != _ADDED_COLUMN else f"NULL AS {_ADDED_COLUMN}"
        for name, _ in target_columns
    )

    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    bind.exec_driver_sql("ALTER TABLE world_events RENAME TO world_events_old")
    bind.exec_driver_sql(create_table)
    bind.exec_driver_sql(
        f"INSERT INTO world_events_new ({target_names}) "
        f"SELECT {select_exprs} FROM world_events_old"
    )
    bind.exec_driver_sql("DROP TABLE world_events_old")
    bind.exec_driver_sql("ALTER TABLE world_events_new RENAME TO world_events")
    for name, columns, unique in _CARRY_OVER_INDEXES:
        keyword = "UNIQUE INDEX" if unique else "INDEX"
        bind.exec_driver_sql(f"CREATE {keyword} {name} ON world_events ({columns})")
    if with_idempotency_key:
        bind.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_world_events_idempotency "
            "ON world_events (idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
    bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    op.add_column(
        "worlds",
        sa.Column("sim_last_advanced_at", sa.DateTime(), nullable=True),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.add_column(
            "world_events",
            sa.Column("idempotency_key", sa.String(100), nullable=True),
        )
        _rebuild_source_check(TARGET_SOURCES, with_idempotency_key=True)
        op.create_index(
            "uq_world_events_idempotency",
            "world_events",
            ["idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )
        return
    # SQLite：重建表时一并带上 idempotency_key 与目标 CHECK（含索引）。
    _rebuild_source_check(TARGET_SOURCES, with_idempotency_key=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_index("uq_world_events_idempotency", table_name="world_events")
        _rebuild_source_check(LEGACY_SOURCES, with_idempotency_key=True)
        op.drop_column("world_events", "idempotency_key")
        op.drop_column("worlds", "sim_last_advanced_at")
        return
    _rebuild_source_check(LEGACY_SOURCES, with_idempotency_key=False)
    op.drop_column("worlds", "sim_last_advanced_at")
