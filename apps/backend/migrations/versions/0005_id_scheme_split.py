"""0005：例外表拆分（雪花 ID + 业务唯一键）与自增表收敛（ADR-16 阶段 D）。

- `conversations`：新增 `session_id` 业务键（存量回填 = 旧 id），存量行 id 保留
  历史会话串，新会话由应用层发雪花。
- `feishu_dedupe_ledger` / `feishu_deliveries`：`event_id` / `idempotency_key` 由主键
  转业务唯一键，新增雪花 `id` 主键；存量行由迁移内**保留机号 1023** 的独立
  Sonyflake 实例回填（与应用实例互斥，不撞号）。
- `ledger_categories`：新增 `seed_key`（播种原始名），种子行回填解析自存量
  `cat_seed_{user_id}_{原始名}` id；跨重命名的稳定身份改由 seed_key 承担。
- `messages` / `emotion_history`：`id` 自增 Integer → 雪花 BigInteger
  （`autoincrement` 关闭；存量自增值原样保留，同列共存）。
"""
from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sonyflake import Sonyflake

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"

_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
_MIGRATION_MACHINE_ID = 1023


def _backfill_generator() -> Sonyflake:
    return Sonyflake(
        start_time=_EPOCH,
        bits_sequence=12,
        bits_machine_id=10,
        time_unit=timedelta(milliseconds=1),
        machine_id=_MIGRATION_MACHINE_ID,
    )


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    op.add_column("conversations", sa.Column("session_id", sa.String(), nullable=True))
    op.execute("UPDATE conversations SET session_id = id WHERE session_id IS NULL")
    op.create_index(
        "uq_conversations_session_id", "conversations", ["session_id"], unique=True
    )

    for table, key_col, ts_col, index_name in (
        ("feishu_dedupe_ledger", "event_id", "received_at", "idx_feishu_dedupe_ledger_received_at"),
        ("feishu_deliveries", "idempotency_key", "delivered_at", "idx_feishu_deliveries_delivered_at"),
    ):
        op.rename_table(table, f"{table}__old")
        op.create_table(
            table,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(key_col, sa.String(), nullable=False, unique=True),
            sa.Column(ts_col, sa.DateTime(), nullable=False),
        )
        generator = _backfill_generator()
        rows = bind.execute(
            sa.text(f"SELECT {key_col}, {ts_col} FROM {table}__old")
        ).fetchall()
        for key, ts in rows:
            bind.execute(
                sa.text(
                    f"INSERT INTO {table} (id, {key_col}, {ts_col}) "
                    "VALUES (:i, :k, :t)"
                ),
                {"i": str(generator.next_id()), "k": key, "t": ts},
            )
        op.drop_table(f"{table}__old")
        op.create_index(index_name, table, [ts_col])

    op.add_column(
        "ledger_categories", sa.Column("seed_key", sa.String(), nullable=True)
    )
    op.execute(
        "UPDATE ledger_categories SET seed_key = SUBSTR(id, LENGTH('cat_seed_' || user_id || '_') + 1) "
        "WHERE is_seed AND id LIKE 'cat_seed_%' AND seed_key IS NULL"
    )
    op.create_index(
        "uq_ledger_categories_user_seed_key",
        "ledger_categories",
        ["user_id", "seed_key"],
        unique=True,
    )

    for table in ("messages", "emotion_history"):
        if is_pg:
            op.execute(f"ALTER TABLE {table} ALTER COLUMN id DROP DEFAULT")
            op.execute(f"DROP SEQUENCE IF EXISTS {table}_id_seq")
            op.alter_column(
                table,
                "id",
                existing_type=sa.Integer(),
                type_=sa.BigInteger(),
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    for table in ("messages", "emotion_history"):
        if is_pg:
            op.alter_column(
                table,
                "id",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
            )

    op.drop_index("uq_ledger_categories_user_seed_key", table_name="ledger_categories")
    op.drop_column("ledger_categories", "seed_key")

    for table, key_col, ts_col, index_name in (
        ("feishu_dedupe_ledger", "event_id", "received_at", "idx_feishu_dedupe_ledger_received_at"),
        ("feishu_deliveries", "idempotency_key", "delivered_at", "idx_feishu_deliveries_delivered_at"),
    ):
        op.rename_table(table, f"{table}__new")
        op.create_table(
            table,
            sa.Column(key_col, sa.String(), primary_key=True),
            sa.Column(ts_col, sa.DateTime(), nullable=False),
        )
        bind.execute(
            sa.text(
                f"INSERT INTO {table} ({key_col}, {ts_col}) "
                f"SELECT {key_col}, {ts_col} FROM {table}__new"
            )
        )
        op.drop_table(f"{table}__new")
        op.create_index(index_name, table, [ts_col])

    op.drop_index("uq_conversations_session_id", table_name="conversations")
    op.drop_column("conversations", "session_id")
