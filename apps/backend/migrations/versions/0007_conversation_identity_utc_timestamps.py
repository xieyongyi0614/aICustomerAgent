"""0007：conversation + identity 域时间列统一 UTC-aware（timestamptz）。

- 两域朴素列（`conversations` / `messages` / `conversation_summaries` / `scene_state` /
  `users` / `channel_identities` / `feishu_dedupe_ledger` / `feishu_deliveries` /
  `briefing_preferences`）存的是部署本地墙钟，按 `Asia/Shanghai` 解释为真实瞬间。
- `conversations.mode_entered_at` 历史为 `timestamptz`，但写入的是朴素本地墙钟
  （被按 UTC 标记），此处先按 UTC 取回墙钟、再按 `Asia/Shanghai` 重建正确瞬间。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"

LOCAL_TZ = "Asia/Shanghai"

_NAIVE_COLUMNS = (
    ("conversations", "created_at"),
    ("conversations", "updated_at"),
    ("messages", "created_at"),
    ("conversation_summaries", "created_at"),
    ("conversation_summaries", "updated_at"),
    ("scene_state", "created_at"),
    ("scene_state", "updated_at"),
    ("users", "created_at"),
    ("users", "updated_at"),
    ("channel_identities", "created_at"),
    ("channel_identities", "updated_at"),
    ("feishu_dedupe_ledger", "received_at"),
    ("feishu_deliveries", "delivered_at"),
    ("briefing_preferences", "updated_at"),
)

_MISLABELED_COLUMNS = (
    ("conversations", "mode_entered_at"),
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
