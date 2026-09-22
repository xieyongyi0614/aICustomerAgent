"""PLA-004 账本域三表：账户 / 类目 / 条目（append-only）。

Revision ID: 0054
Revises: 0053
Create Date: 2026-09-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ledger_accounts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "type IN ('cash', 'bank', 'ewallet', 'credit', 'other')",
            name="ck_ledger_accounts_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_ledger_accounts_status",
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_ledger_accounts_user_name"),
    )
    op.create_index(
        "ix_ledger_accounts_user", "ledger_accounts", ["user_id", "status"]
    )

    op.create_table(
        "ledger_categories",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("is_seed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('expense', 'income')",
            name="ck_ledger_categories_kind",
        ),
        sa.UniqueConstraint(
            "user_id",
            "parent_id",
            "name",
            name="uq_ledger_categories_user_parent_name",
        ),
    )
    op.create_index(
        "ix_ledger_categories_user", "ledger_categories", ["user_id", "kind"]
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("merchant", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("reversal_of", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "amount_minor > 0",
            name="ck_ledger_entries_amount_minor",
        ),
        sa.CheckConstraint(
            "direction IN ('expense', 'income', 'transfer')",
            name="ck_ledger_entries_direction",
        ),
        sa.CheckConstraint(
            "source IN ('conversation', 'action', 'manual', 'import')",
            name="ck_ledger_entries_source",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["ledger_accounts.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["ledger_categories.id"]),
        sa.ForeignKeyConstraint(["reversal_of"], ["ledger_entries.id"]),
    )
    op.create_index(
        "ix_ledger_entries_user_time", "ledger_entries", ["user_id", "occurred_at"]
    )
    op.create_index(
        "ix_ledger_entries_user_cat", "ledger_entries", ["user_id", "category_id"]
    )
    op.create_index("ix_ledger_entries_reversal", "ledger_entries", ["reversal_of"])


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_reversal", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_user_cat", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_user_time", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    op.drop_index("ix_ledger_categories_user", table_name="ledger_categories")
    op.drop_table("ledger_categories")
    op.drop_index("ix_ledger_accounts_user", table_name="ledger_accounts")
    op.drop_table("ledger_accounts")
