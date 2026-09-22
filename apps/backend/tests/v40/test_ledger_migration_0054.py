from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from app.core.db import (
    Base,
    LedgerAccountRow,
    LedgerCategoryRow,
    LedgerEntryRow,
)
from tests.support.schema_pins import (
    MIGRATION_HEAD,
    SCHEMA_PREVIOUS_HEAD,
    SCHEMA_TABLE_COUNT,
    schema_pin,
)

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION_PATH = BACKEND / "migrations" / "versions" / "0054_life_ledger_domain.py"


def _account(db, *, user_id="u1", name="现金"):
    now = datetime.now()
    row = LedgerAccountRow(
        id=f"acc-{user_id}-{name}",
        user_id=user_id,
        name=name,
        type="cash",
        currency="CNY",
        status="active",
        created_at=now,
        updated_at=now,
    )
    with db() as session:
        session.add(row)
        session.commit()
    return row


def _entry(db, *, key="k1", amount=2000, direction="expense", reversal_of=None):
    now = datetime.now()
    row = LedgerEntryRow(
        id=f"ent-{key}",
        user_id="u1",
        account_id="acc-u1-现金",
        category_id=None,
        amount_minor=amount,
        currency="CNY",
        direction=direction,
        occurred_at=now,
        source="manual",
        source_ref=None,
        idempotency_key=key,
        reversal_of=reversal_of,
        created_at=now,
    )
    with db() as session:
        session.add(row)
        session.commit()
    return row


def test_orm_has_three_ledger_tables():
    tables = Base.metadata.tables
    for name in ("ledger_accounts", "ledger_categories", "ledger_entries"):
        assert name in tables
    assert set(tables["ledger_accounts"].columns.keys()) >= {
        "id",
        "user_id",
        "name",
        "type",
        "currency",
        "status",
    }
    assert set(tables["ledger_entries"].columns.keys()) >= {
        "amount_minor",
        "direction",
        "idempotency_key",
        "reversal_of",
        "occurred_at",
    }


def test_migration_chain_head_is_0054():
    config = Config(str(BACKEND / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [MIGRATION_HEAD]
    revision = script.get_revision(MIGRATION_HEAD)
    assert revision is not None
    assert revision.down_revision == SCHEMA_PREVIOUS_HEAD == "0053"


def test_schema_table_count_is_49():
    assert SCHEMA_TABLE_COUNT == 49
    assert len(Base.metadata.tables) == SCHEMA_TABLE_COUNT
    assert schema_pin().schema_table_count == 49


def test_amount_minor_is_integer():
    column = LedgerEntryRow.__table__.columns["amount_minor"]
    assert type(column.type).__name__ == "Integer"


def test_no_ttl_or_decay_columns():
    banned = ("expires_at", "ttl", "decay", "salience", "expired")
    for table in (
        LedgerAccountRow.__table__,
        LedgerCategoryRow.__table__,
        LedgerEntryRow.__table__,
    ):
        for name in table.columns.keys():
            for token in banned:
                assert token not in name.lower()


def test_idempotency_key_unique(db_session_factory):
    _account(db_session_factory)
    _entry(db_session_factory, key="dup")
    with pytest.raises(IntegrityError):
        _entry(db_session_factory, key="dup")


def test_positive_amount_check_enforced(db_session_factory):
    _account(db_session_factory)
    for amount in (0, -5):
        now = datetime.now()
        with db_session_factory() as session:
            session.add(
                LedgerEntryRow(
                    id=f"bad-{amount}",
                    user_id="u1",
                    account_id="acc-u1-现金",
                    amount_minor=amount,
                    currency="CNY",
                    direction="expense",
                    occurred_at=now,
                    source="manual",
                    idempotency_key=f"bad-{amount}",
                    created_at=now,
                )
            )
            with pytest.raises(Exception):
                session.commit()
            session.rollback()


def test_direction_check_enforced(db_session_factory):
    _account(db_session_factory)
    now = datetime.now()
    with db_session_factory() as session:
        session.add(
            LedgerEntryRow(
                id="bad-dir",
                user_id="u1",
                account_id="acc-u1-现金",
                amount_minor=100,
                currency="CNY",
                direction="spend",
                occurred_at=now,
                source="manual",
                idempotency_key="bad-dir",
                created_at=now,
            )
        )
        with pytest.raises(Exception):
            session.commit()
        session.rollback()


def test_reversal_fk_enforced(db_session_factory):
    fks = list(LedgerEntryRow.__table__.foreign_keys)
    targets = {fk.target_fullname for fk in fks}
    assert "ledger_entries.id" in targets
    assert "ledger_accounts.id" in targets
    _account(db_session_factory)
    now = datetime.now()
    with db_session_factory() as session:
        session.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys = ON"))
        session.add(
            LedgerEntryRow(
                id="bad-rev",
                user_id="u1",
                account_id="acc-u1-现金",
                amount_minor=100,
                currency="CNY",
                direction="expense",
                occurred_at=now,
                source="manual",
                idempotency_key="bad-rev",
                reversal_of="missing-entry",
                created_at=now,
            )
        )
        try:
            session.commit()
        except Exception:
            session.rollback()
            return
        session.rollback()
        engine = session.get_bind()
        if engine.dialect.name == "sqlite":
            pytest.skip("内存 SQLite 未强制 FK；PG 迁移用例覆盖强制路径")
        raise AssertionError("reversal_of 悬空引用未被拒绝")


def test_migration_has_upgrade_and_downgrade():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "def upgrade()" in source
    assert "def downgrade()" in source
    for table in ("ledger_accounts", "ledger_categories", "ledger_entries"):
        assert f'"{table}"' in source
    drop_order = [
        source.index('op.drop_table("ledger_entries")'),
        source.index('op.drop_table("ledger_categories")'),
        source.index('op.drop_table("ledger_accounts")'),
    ]
    assert drop_order == sorted(drop_order)


def test_check_constraints_are_boolean_expressions():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    expressions = re.findall(
        r"CheckConstraint\(\s*\"([^\"]+)\"",
        source,
    )
    assert expressions
    for expr in expressions:
        assert any(op in expr for op in (">", "<", "=", "IN", "LIKE")), expr
