from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.ledger import (
    LedgerAmountError,
    LedgerEntryDraft,
    to_major,
    to_minor,
)

BACKEND = Path(__file__).resolve().parents[2]
LEDGER_MODEL = BACKEND / "app" / "models" / "ledger.py"


def test_to_minor_exact():
    assert to_minor("20") == 2000
    assert to_minor(Decimal("20.00")) == 2000
    assert to_minor(Decimal("0.01")) == 1
    assert to_minor(20) == 2000


def test_to_minor_rejects_float():
    with pytest.raises(LedgerAmountError):
        to_minor(20.0)
    with pytest.raises(LedgerAmountError):
        to_minor(0.1)


def test_minor_major_roundtrip_lossless():
    for cents in range(1, 1001):
        major = to_major(cents)
        assert to_minor(major) == cents
        assert to_minor(str(major)) == cents


def test_direction_enum_domain():
    with pytest.raises(ValidationError):
        LedgerEntryDraft(
            user_id="u",
            account_id="a",
            amount_minor=100,
            direction="spend",
            occurred_at="2026-09-22T12:00:00",
            source="manual",
            idempotency_key="k1",
        )


def test_source_enum_domain():
    with pytest.raises(ValidationError):
        LedgerEntryDraft(
            user_id="u",
            account_id="a",
            amount_minor=100,
            direction="expense",
            occurred_at="2026-09-22T12:00:00",
            source="dream",
            idempotency_key="k2",
        )


def test_ledger_entry_draft_requires_positive_amount():
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            LedgerEntryDraft(
                user_id="u",
                account_id="a",
                amount_minor=bad,
                direction="expense",
                occurred_at="2026-09-22T12:00:00",
                source="manual",
                idempotency_key=f"k-{bad}",
            )


def test_ledger_model_module_has_no_io():
    source = LEDGER_MODEL.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in (
        "app.repositories",
        "app.services",
        "app.chains",
        "app.prompts",
        "sqlalchemy",
        "app.core.db",
    ):
        assert not any(
            name == banned or name.startswith(banned + ".") for name in imported
        )
    assert "SessionLocal" not in source


def test_ledger_settings_has_no_enabled_flag():
    from app.core.settings.ledger import LedgerSettings

    assert not any(name.endswith("_enabled") for name in LedgerSettings.model_fields)
    assert LedgerSettings.model_fields["ledger_default_currency"].default == "CNY"


def test_no_float_in_ledger_paths():
    source = LEDGER_MODEL.read_text(encoding="utf-8")
    assert "float(" not in source
    assert "amount_minor: float" not in source
    assert "amount: float" not in source
    assert "-> float" not in source
