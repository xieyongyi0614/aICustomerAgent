from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.ledger import (
    LedgerReversalError,
    LedgerValidationError,
    ensure_user_bootstrap,
    record_entry,
    reverse_entry,
)

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "ledger-user"


@pytest.fixture()
def bootstrapped():
    report = ensure_user_bootstrap(USER, now=NOW)
    account = ledger_repository.list_accounts(USER)[0]
    return report, account


def _draft(account_id: str, *, amount=2000, direction="expense", key="k1"):
    return LedgerEntryDraft(
        user_id=USER,
        account_id=account_id,
        amount_minor=amount,
        direction=direction,
        occurred_at=NOW,
        source="manual",
        source_ref="src-1",
        idempotency_key=key,
    )


def test_create_entry_returns_created_true(bootstrapped):
    _, account = bootstrapped
    outcome = record_entry(_draft(account.id), idempotency_key="k1", now=NOW)
    assert outcome.created is True
    assert outcome.reason == "created"
    assert ledger_repository.count_entries(USER) == 1


def test_create_entry_idempotent_hit_returns_existing(bootstrapped):
    _, account = bootstrapped
    first = record_entry(_draft(account.id), idempotency_key="k1", now=NOW)
    second = record_entry(_draft(account.id), idempotency_key="k1", now=NOW)
    assert second.created is False
    assert second.reason == "idempotent_hit"
    assert second.entry.id == first.entry.id
    assert ledger_repository.count_entries(USER) == 1


def test_create_entry_different_key_creates_second_row(bootstrapped):
    _, account = bootstrapped
    record_entry(_draft(account.id, key="k1"), idempotency_key="k1", now=NOW)
    record_entry(_draft(account.id, key="k2"), idempotency_key="k2", now=NOW)
    assert ledger_repository.count_entries(USER) == 2


def test_entry_id_is_snowflake_not_idempotency_key(bootstrapped):
    """ADR-16：分录主键是独立身份（雪花），不再由幂等键加前缀派生。"""
    _, account = bootstrapped
    entry = record_entry(
        _draft(account.id, key="snow-1"), idempotency_key="snow-1", now=NOW
    ).entry
    assert entry.id.isdigit(), entry.id
    assert len(entry.id) >= 16
    assert entry.id != "snow-1"
    assert entry.id != f"ent_{entry.idempotency_key}"
    assert entry.idempotency_key == "snow-1"


def test_same_idempotency_key_across_users_records_both(bootstrapped):
    """回归：幂等键材料不含 user_id，全局唯一会让后写者被当作幂等命中而丢账。"""
    _, account = bootstrapped
    other_user = "ledger-other-user"
    ensure_user_bootstrap(other_user, now=NOW)
    other_account = ledger_repository.list_accounts(other_user)[0]

    first = record_entry(
        _draft(account.id, key="shared-key"), idempotency_key="shared-key", now=NOW
    )
    second = record_entry(
        LedgerEntryDraft(
            user_id=other_user,
            account_id=other_account.id,
            amount_minor=2000,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            source_ref="src-2",
            idempotency_key="shared-key",
        ),
        idempotency_key="shared-key",
        now=NOW,
    )

    assert second.created is True, "另一用户同键必须各记一笔"
    assert second.entry.user_id == other_user
    assert second.entry.id != first.entry.id
    assert ledger_repository.count_entries(other_user) == 1
    assert ledger_repository.count_entries(USER) == 1


def test_category_alias_persisted_as_utf8_not_escaped(
    bootstrapped, db_session_factory
):
    """JSON 列改为 UTF-8 直存：别名在库里就是中文（排障 / 文本检索才可用）。

    原先走 Python `json.dumps` 默认 `ensure_ascii=True`，库里存成 `\\uXXXX`：
    应用读回无损，但 `aliases::text LIKE '%滴滴%'` 查不到、人工查库不可读。
    """
    from sqlalchemy import text

    row = next(
        row for row in ledger_repository.list_categories(USER) if row.name == "打车"
    )
    with db_session_factory() as session:
        raw = session.execute(
            text("SELECT aliases FROM ledger_categories WHERE id = :i"), {"i": row.id}
        ).scalar()
    assert "滴滴" in str(raw)
    assert "\\u" not in str(raw)


def test_reverse_entry_keeps_original_untouched(bootstrapped):
    _, account = bootstrapped
    original = record_entry(_draft(account.id), idempotency_key="k1", now=NOW).entry
    snapshot = (
        original.id,
        original.amount_minor,
        original.direction,
        original.reversal_of,
        original.idempotency_key,
    )
    reverse_entry(original.id, reason="记错", idempotency_key="rev-1", now=NOW)
    reloaded = ledger_repository.get_entry(original.id)
    assert (
        reloaded.id,
        reloaded.amount_minor,
        reloaded.direction,
        reloaded.reversal_of,
        reloaded.idempotency_key,
    ) == snapshot


def test_reverse_entry_net_zero(bootstrapped):
    _, account = bootstrapped
    original = record_entry(
        _draft(account.id, amount=2000), idempotency_key="k1", now=NOW
    ).entry
    reverse_entry(original.id, reason="冲正", idempotency_key="rev-1", now=NOW)
    entries = ledger_repository.list_entries(USER)
    net = 0
    for row in entries:
        sign = 1 if row.direction == "income" else -1
        net += sign * row.amount_minor
    assert net == 0
    assert len(entries) == 2


def test_reverse_entry_is_idempotent(bootstrapped):
    _, account = bootstrapped
    original = record_entry(_draft(account.id), idempotency_key="k1", now=NOW).entry
    first = reverse_entry(original.id, reason="r", idempotency_key="rev-1", now=NOW)
    second = reverse_entry(original.id, reason="r", idempotency_key="rev-1", now=NOW)
    assert second.created is False
    assert second.entry.id == first.entry.id
    assert ledger_repository.count_entries(USER) == 2


def test_reverse_of_reversal_is_rejected(bootstrapped):
    _, account = bootstrapped
    original = record_entry(_draft(account.id), idempotency_key="k1", now=NOW).entry
    reversal = reverse_entry(
        original.id, reason="r", idempotency_key="rev-1", now=NOW
    ).entry
    with pytest.raises(LedgerReversalError):
        reverse_entry(reversal.id, reason="r2", idempotency_key="rev-2", now=NOW)


def test_ensure_default_account_idempotent(bootstrapped):
    for _ in range(3):
        ensure_user_bootstrap(USER, now=NOW)
    assert len(ledger_repository.list_accounts(USER)) == 1


def test_ensure_seed_categories_idempotent(bootstrapped):
    first = ledger_repository.list_categories(USER)
    ensure_user_bootstrap(USER, now=NOW)
    second = ledger_repository.list_categories(USER)
    assert len(first) == len(second)


def test_seed_does_not_overwrite_user_renamed_category(bootstrapped, db_session_factory):
    from app.core.db import LedgerCategoryRow

    categories = ledger_repository.list_categories(USER)
    target = next(row for row in categories if row.name == "餐饮")
    with db_session_factory() as session:
        row = session.get(LedgerCategoryRow, target.id)
        row.name = "吃饭"
        session.commit()
    before = len(ledger_repository.list_categories(USER))
    ensure_user_bootstrap(USER, now=NOW)
    after = ledger_repository.list_categories(USER)
    assert len(after) == before
    assert any(row.name == "吃饭" for row in after)


def test_record_entry_rejects_foreign_account(bootstrapped):
    ensure_user_bootstrap("other-user", now=NOW)
    other_account = ledger_repository.list_accounts("other-user")[0]
    with pytest.raises(LedgerValidationError):
        record_entry(_draft(other_account.id), idempotency_key="foreign", now=NOW)


def test_record_entry_rejects_non_positive_amount(bootstrapped):
    _, account = bootstrapped
    for amount in (0, -1):
        with pytest.raises(Exception):
            draft = _draft(account.id, amount=amount, key=f"bad-{amount}")
            record_entry(draft, idempotency_key=f"bad-{amount}", now=NOW)


def test_no_bypass_write_static():
    offenders = []
    for path in (BACKEND / "app").rglob("*.py"):
        if path.name == "ledger_repository.py":
            continue
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if "INSERT INTO ledger_" in source or "UPDATE ledger_entries" in source:
            offenders.append(str(path))
    assert offenders == []


def test_repository_has_no_business_judgment():
    source = (BACKEND / "app" / "repositories" / "ledger_repository.py").read_text(
        encoding="utf-8"
    )
    assert "app.services" not in source
    assert "from app.services" not in source
