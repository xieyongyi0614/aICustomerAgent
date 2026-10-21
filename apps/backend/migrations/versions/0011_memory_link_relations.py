"""0011：`memory_links.relation` 值域扩展（`caused_by` / `before` / `related`）。

既有三值（supersedes / merges / contradicts）保持在前，新增三值追加在后；只替换 CHECK，
表数与列摘要不变。降级时旧 CHECK 无法表达新值，先删除新值行再重建三值约束
（结构可逆；数据不反向还原，对齐 `0010` 的降级纪律）。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"

LINK_TABLE = "memory_links"
LINK_RELATION_CONSTRAINT = "ck_memory_links_relation"

LEGACY_RELATIONS: tuple[str, ...] = (
    "supersedes",
    "merges",
    "contradicts",
)
NEW_RELATIONS: tuple[str, ...] = ("caused_by", "before", "related")
RELATIONS: tuple[str, ...] = (*LEGACY_RELATIONS, *NEW_RELATIONS)


def _relation_clause(relations: tuple[str, ...] = RELATIONS) -> str:
    # 必须传完整布尔式（仓库已知陷阱：传值清单会在 PG 上 DatatypeMismatch）
    return "relation IN (" + ", ".join(f"'{value}'" for value in relations) + ")"


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _replace_check(clause: str) -> None:
    if _is_sqlite():
        with op.batch_alter_table(LINK_TABLE, recreate="always") as batch:
            batch.drop_constraint(LINK_RELATION_CONSTRAINT, type_="check")
            batch.create_check_constraint(LINK_RELATION_CONSTRAINT, clause)
        return
    op.drop_constraint(
        LINK_RELATION_CONSTRAINT, LINK_TABLE, type_="check"
    )
    op.create_check_constraint(
        LINK_RELATION_CONSTRAINT, LINK_TABLE, clause
    )


def upgrade() -> None:
    _replace_check(_relation_clause(RELATIONS))


def downgrade() -> None:
    op.execute(
        f"DELETE FROM {LINK_TABLE} WHERE {_relation_clause(NEW_RELATIONS)}"
    )
    _replace_check(_relation_clause(LEGACY_RELATIONS))
