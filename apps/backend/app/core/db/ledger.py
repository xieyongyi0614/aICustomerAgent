"""账本域模型：账户、分类、分录与生活任务。"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class LedgerAccountRow(Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY", server_default="CNY"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_ledger_accounts_user_name"),
        CheckConstraint(
            "type IN ('cash', 'bank', 'ewallet', 'credit', 'other')",
            name="ck_ledger_accounts_type",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_ledger_accounts_status",
        ),
        Index("ix_ledger_accounts_user", "user_id", "status"),
    )


class LedgerCategoryRow(Base):
    __tablename__ = "ledger_categories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    seed_key: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_seed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "parent_id",
            "name",
            name="uq_ledger_categories_user_parent_name",
        ),
        Index(
            "uq_ledger_categories_user_seed_key",
            "user_id",
            "seed_key",
            unique=True,
        ),
        CheckConstraint(
            "kind IN ('expense', 'income')",
            name="ck_ledger_categories_kind",
        ),
        Index("ix_ledger_categories_user", "user_id", "kind"),
    )


class LedgerEntryRow(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    account_id: Mapped[str] = mapped_column(
        String, ForeignKey("ledger_accounts.id"), nullable=False
    )
    category_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("ledger_categories.id"), nullable=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY", server_default="CNY"
    )
    direction: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    merchant: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    reversal_of: Mapped[str | None] = mapped_column(
        String, ForeignKey("ledger_entries.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "amount_minor > 0",
            name="ck_ledger_entries_amount_minor",
        ),
        CheckConstraint(
            "direction IN ('expense', 'income', 'transfer')",
            name="ck_ledger_entries_direction",
        ),
        CheckConstraint(
            "source IN ('conversation', 'action', 'manual', 'import')",
            name="ck_ledger_entries_source",
        ),
        Index("ix_ledger_entries_user_time", "user_id", "occurred_at"),
        Index("ix_ledger_entries_user_cat", "user_id", "category_id"),
        Index("ix_ledger_entries_reversal", "reversal_of"),
    )


class LifeTaskRow(Base):
    __tablename__ = "life_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(
        String, nullable=False, default="task", server_default="task"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="open", server_default="open"
    )
    tag: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    order_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_date: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('task', 'memo')", name="ck_life_tasks_kind"),
        CheckConstraint(
            "status IN ('open', 'done', 'cancelled')",
            name="ck_life_tasks_status",
        ),
        Index("ix_life_tasks_user_status", "user_id", "status"),
        Index("ix_life_tasks_user_remind", "user_id", "remind_at"),
    )
