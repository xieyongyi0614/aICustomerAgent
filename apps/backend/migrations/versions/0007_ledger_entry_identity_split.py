"""0007：账本分录「主键 = 幂等键」解耦，幂等唯一范围收敛到 per-user。

背景：`ledger_entries.id` 此前由 `f"ent_{idempotency_key}"` 派生，于是分录身份被
内容派生键绑定，且幂等命中判定天然是**全局**的：

- 幂等键材料（`services/action/detector.py` 的 `record_ledger_entry` 核心参数、
  `services/ledger/confirmation.py` 的 `pending_key`）不含 `user_id`；
- 唯一约束是 `UNIQUE (idempotency_key)`，查重也不带 `user_id`；
- 后果：两个用户产生同一内容派生键时互相吞账——先写者占键，后写者被当作幂等
  命中返回，自己的账目静默丢失并拿到对方的 entry_id。

本迁移只收敛约束面：

- `id` 改由应用层发雪花（`ids.new_id_str()`），**存量行 id 原样保留**：引用面除
  `ledger_entries.reversal_of` 与 `car_service_records.ledger_entry_id` 外，
  还散落在观测/行动载荷的 JSON 里（`ledger.entry_id` 观测字段、能力结果载荷），
  重映射的收益远小于静默改历史的风险。
- 幂等唯一性由 `UNIQUE (idempotency_key)` 收敛为 `UNIQUE (user_id, idempotency_key)`。

原约束为全局唯一，故 per-user 组合不可能出现重复，本迁移无数据前置冲突。

方言差异：基线 `0001` 把旧约束声明为**匿名** `sa.UniqueConstraint('idempotency_key')`
——PG 会自动命名为 `ledger_entries_idempotency_key_key`，SQLite 则没有名字。SQLite
的批处理重建会把匿名约束原样带过去，故 SQLite 分支显式给出「摘掉旧约束」的表副本。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"

TABLE = "ledger_entries"
COMPOSITE_NAME = "uq_ledger_entries_user_idempotency"
LEGACY_NAME = "ledger_entries_idempotency_key_key"
ID_COLUMNS = ("user_id", "idempotency_key")


def _copy_without_unique_on(bind, columns: tuple[str, ...]) -> sa.Table:
    """反映表的同时摘掉覆盖 `columns` 的唯一约束（SQLite 匿名约束只能这样去）。"""
    metadata = sa.MetaData()
    table = sa.Table(TABLE, metadata, autoload_with=bind)
    dropped = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.UniqueConstraint)
        and [column.name for column in constraint.columns] == list(columns)
    ]
    for constraint in dropped:
        table.constraints.discard(constraint)
    return table


def _legacy_unique_name(bind) -> str | None:
    """旧全局约束名（PG 自动命名；SQLite 匿名 → 返回 None）。"""
    for constraint in sa.inspect(bind).get_unique_constraints(TABLE):
        if list(constraint.get("column_names") or []) == [ID_COLUMNS[1]]:
            return constraint.get("name")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        name = _legacy_unique_name(bind)
        if name is not None:
            op.drop_constraint(name, TABLE, type_="unique")
        op.create_unique_constraint(COMPOSITE_NAME, TABLE, list(ID_COLUMNS))
        return
    copy_from = _copy_without_unique_on(bind, (ID_COLUMNS[1],))
    with op.batch_alter_table(TABLE, copy_from=copy_from) as batch:
        batch.create_unique_constraint(COMPOSITE_NAME, list(ID_COLUMNS))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(COMPOSITE_NAME, TABLE, type_="unique")
        op.create_unique_constraint(LEGACY_NAME, TABLE, [ID_COLUMNS[1]])
        return
    copy_from = _copy_without_unique_on(bind, ID_COLUMNS)
    with op.batch_alter_table(TABLE, copy_from=copy_from) as batch:
        batch.create_unique_constraint(LEGACY_NAME, [ID_COLUMNS[1]])
