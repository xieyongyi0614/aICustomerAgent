"""迁移链头钉测单点入口（PLA-001；2026-09-29 迁移链折叠为单迁移 0001，0002 起增量）。

全仓唯一定义：`MIGRATION_HEAD` / `SCHEMA_TABLE_COUNT` /
`SCHEMA_COLUMNS_DIGEST`。其余测试一律 import，禁止本地字面量定义。
升级迁移时只改本模块（+ 迁移文件本身），目标改动文件数 ≤ 3。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

MIGRATION_HEAD = "0008"
MIGRATION_HEAD_PARENT = "0007"
BASELINE_MIGRATION_REVISION = "0001"
SCHEMA_TABLE_COUNT = 55
SCHEMA_COLUMNS_DIGEST = "720e6995b95cfc22"


@dataclass(frozen=True, slots=True)
class SchemaPin:
    migration_head: str
    schema_table_count: int
    schema_columns_digest: str


def schema_pin() -> SchemaPin:
    return SchemaPin(
        migration_head=MIGRATION_HEAD,
        schema_table_count=SCHEMA_TABLE_COUNT,
        schema_columns_digest=SCHEMA_COLUMNS_DIGEST,
    )


def _digest_lines(lines) -> str:
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()[:16]


def table_column_digest(table) -> str:
    return _digest_lines(
        "{}:{}:{}:{}".format(
            column.name, str(column.type), column.nullable, bool(column.primary_key)
        )
        for column in table.columns
    )


def schema_columns_digest(exclude_tables: tuple[str, ...] = ()) -> str:
    from app.core.db import Base

    return _digest_lines(
        "{}:{}".format(name, table_column_digest(table))
        for name, table in Base.metadata.tables.items()
        if name not in exclude_tables
    )


def table_set_digest() -> str:
    from app.core.db import Base

    return _digest_lines(sorted(Base.metadata.tables))
