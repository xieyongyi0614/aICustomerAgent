"""0006：memory 域时间列统一 UTC-aware（timestamptz）。

- `memories` / `memory_candidates` / `memory_links` 的朴素列（`created_at` /
  `updated_at` / `last_accessed_at` / `expires_at`）存的是部署本地墙钟，按
  `Asia/Shanghai` 解释为真实瞬间。
- `memories` 的 `last_reinforced_at` / `last_decayed_at` / `forgotten_at` 历史为
  `timestamptz`，但写入的是朴素本地墙钟（被按 UTC 标记），此处先按 UTC 取回
  墙钟、再按 `Asia/Shanghai` 重建正确瞬间。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"

LOCAL_TZ = "Asia/Shanghai"

_NAIVE_COLUMNS = (
    ("memories", "created_at"),
    ("memories", "updated_at"),
    ("memories", "last_accessed_at"),
    ("memories", "expires_at"),
    ("memory_candidates", "created_at"),
    ("memory_links", "created_at"),
)

_MISLABELED_COLUMNS = (
    ("memories", "last_reinforced_at"),
    ("memories", "last_decayed_at"),
    ("memories", "forgotten_at"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _NAIVE_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING ({column} AT TIME ZONE '{LOCAL_TZ}')"
        )
    for table, column in _MISLABELED_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING ({column} AT TIME ZONE 'UTC' AT TIME ZONE '{LOCAL_TZ}')"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _MISLABELED_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING ({column} AT TIME ZONE '{LOCAL_TZ}' AT TIME ZONE 'UTC')"
        )
    for table, column in _NAIVE_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE timestamp "
            f"USING ({column} AT TIME ZONE '{LOCAL_TZ}')"
        )
