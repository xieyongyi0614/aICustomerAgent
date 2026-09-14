"""TOOL-009 V2.4.0 反思工具效能 Insight 类型值域放宽。

`ck_insights_type` 原值域只有 belief/preference/pattern（0025 落地）。TOOL-009 新增
三类工具效能 Insight（capability_note / usage_preference / interaction_calibration），
只放宽该 CHECK 值域——无新表、无新列、无索引变更（唯一结构变更点）。

约束值域变更无法用 ALTER 完成，两方言处理方式不同（对齐 0045 同款裁决）：
- PostgreSQL：DROP CONSTRAINT + CREATE CHECK（原生支持）。
- SQLite：表级重建。此处**不走 batch_alter_table**——batch 模式会反射既有具名
  CHECK/索引并在临时表上重建，其 INSERT ... SELECT 在 SQLite 上会触发
  "row value misused"（0045 实测）。改为手写 rename → create → copy → drop 序列。

Revision ID: 0046
Revises: 0045
Create Date: 2026-09-14

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_TYPES = "('belief', 'preference', 'pattern')"
TARGET_TYPES = (
    "('belief', 'preference', 'pattern',"
    " 'capability_note', 'usage_preference', 'interaction_calibration')"
)

_INSIGHTS_COLUMNS = (
    ("id", "VARCHAR NOT NULL"),
    ("user_id", "VARCHAR NOT NULL"),
    ("character_id", "VARCHAR NOT NULL DEFAULT 'asuna'"),
    ("statement", "TEXT NOT NULL"),
    ("type", "VARCHAR NOT NULL"),
    ("confidence", "FLOAT NOT NULL"),
    ("scope", "VARCHAR NOT NULL"),
    ("status", "VARCHAR NOT NULL DEFAULT 'active'"),
    ("run_id", "VARCHAR"),
    ("created_at", "DATETIME NOT NULL"),
    ("updated_at", "DATETIME NOT NULL"),
    ("invalidated_at", "DATETIME"),
    ("invalidated_reason", "TEXT"),
    ("superseded_by", "VARCHAR"),
)

_CARRY_OVER_INDEXES = (
    ("idx_insights_user_status", "user_id, status"),
    ("idx_insights_user_scope_status", "user_id, scope, status"),
)


def _rebuild_type_check(target_types: str) -> None:
    """放宽 insights.type 值域 CHECK（方言按 PostgreSQL / SQLite 分流）。"""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_insights_type", "insights", type_="check")
        op.create_check_constraint("ck_insights_type", "insights", f"type IN {target_types}")
        return
    _sqlite_rebuild_insights(target_types)


def _assert_rows_within(types: str) -> None:
    """降级前置校验：既有行必须落在目标值域内（SQLite 手写重建无事务回滚，先校验再动 DDL）。"""
    bind = op.get_bind()
    incompatible = bind.exec_driver_sql(
        f"SELECT count(*) FROM insights WHERE type NOT IN {types}"
    ).scalar()
    if incompatible:
        raise RuntimeError(
            f"downgrade 前置校验失败：insights 有 {incompatible} 行使用值域外类型；"
            "请先清理这些工具效能 Insight 再降级（本迁移不静默丢数据）"
        )


def _sqlite_rebuild_insights(type_check: str) -> None:
    """SQLite：手写表重建，等价于 batch_alter_table 且规避 row value misused。"""
    bind = op.get_bind()
    column_ddl = ", ".join(f"{name} {ddl}" for name, ddl in _INSIGHTS_COLUMNS)
    create_table = (
        f"CREATE TABLE insights_new ({column_ddl}, "
        f"PRIMARY KEY (id), "
        f"CONSTRAINT ck_insights_status "
        f"CHECK (status IN ('active', 'superseded', 'invalidated')), "
        f"CONSTRAINT ck_insights_type CHECK (type IN {type_check}), "
        f"CONSTRAINT ck_insights_scope "
        f"CHECK (scope IN ('user', 'relationship', 'world')), "
        f"CONSTRAINT ck_insights_invalidated_reason "
        f"CHECK (status != 'invalidated' OR invalidated_reason IS NOT NULL))"
    )
    target_names = ", ".join(name for name, _ in _INSIGHTS_COLUMNS)

    bind.exec_driver_sql("PRAGMA foreign_keys=OFF")
    bind.exec_driver_sql("ALTER TABLE insights RENAME TO insights_old")
    bind.exec_driver_sql(create_table)
    bind.exec_driver_sql(
        f"INSERT INTO insights_new ({target_names}) "
        f"SELECT {target_names} FROM insights_old"
    )
    bind.exec_driver_sql("DROP TABLE insights_old")
    bind.exec_driver_sql("ALTER TABLE insights_new RENAME TO insights")
    for name, columns in _CARRY_OVER_INDEXES:
        bind.exec_driver_sql(f"CREATE INDEX {name} ON insights ({columns})")
    bind.exec_driver_sql("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    _rebuild_type_check(TARGET_TYPES)


def downgrade() -> None:
    _assert_rows_within(LEGACY_TYPES)
    _rebuild_type_check(LEGACY_TYPES)
