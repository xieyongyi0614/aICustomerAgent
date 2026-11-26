"""0008：`ledger_categories.aliases` 存量转义规范化（中文直存）。

背景：`aliases` 是 PG `json` 列（原样存文本、不做规范化），历史写入走 Python
`json.dumps` 的默认参数 `ensure_ascii=True`，于是中文别名在库里存成
`"\\u6ef4\\u6ef4"` 形态。应用侧 `json.loads` 读回无碍（匹配、展示都正常），但：

- 人工查库 / 排障不可读（实测已踩）；
- `aliases::text LIKE '%滴滴%'` 这类 SQL 文本检索查不到。

`core/db/engine.py` 已改 `json_serializer`（`ensure_ascii=False`，新写入即中文），
本迁移把存量解回中文：`(aliases::jsonb)::json` 先按 JSON 语义解码转义，再按
UTF-8 直出。

范围：只处理 `ledger_categories.aliases`（唯一的「给人看」的 JSON 列）；其余 JSON
列（事件 / 行动 / 记忆 / 观测载荷）都是机器读写，保留原样转义，需要时另开批次。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"

TABLE = "ledger_categories"
COLUMN = "aliases"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        f"UPDATE {TABLE} SET {COLUMN} = ({COLUMN}::jsonb)::json "
        f"WHERE {COLUMN} IS NOT NULL AND {COLUMN}::text LIKE '%\\u%'"
    )


def downgrade() -> None:
    """规范化是单向的：重新转义没有语义价值，不做反向数据改写。"""
