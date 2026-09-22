from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.ledger import (
    ensure_user_bootstrap,
    format_minor,
    record_entry,
    reverse_entry,
    summary,
    top_categories,
)
from app.services.ledger.query import Period, list_entries, trend

TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=TZ)
USER = "query-user"
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture()
def account():
    ensure_user_bootstrap(USER, now=NOW.replace(tzinfo=None))
    return ledger_repository.list_accounts(USER)[0]


def _entry(account_id, *, amount, direction="expense", when, key, category_id=None):
    return record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=account_id,
            category_id=category_id,
            amount_minor=amount,
            direction=direction,
            occurred_at=when,
            source="manual",
            source_ref=key,
            idempotency_key=key,
        ),
        idempotency_key=key,
        now=when,
    ).entry


def test_summary_matches_manual_computation(account):
    amounts = [100, 250, 999, 1, 5000, 33, 77, 1200, 45, 88, 66, 10, 20, 30, 40, 50, 60, 70, 80, 90]
    for i, amount in enumerate(amounts):
        direction = "income" if i % 5 == 0 else "expense"
        _entry(
            account.id,
            amount=amount,
            direction=direction,
            when=NOW + timedelta(hours=i),
            key=f"m{i}",
        )
    period = Period.month(NOW, tz=TZ)
    result = summary(USER, period=period, compare_previous=False)
    manual_expense = sum(a for i, a in enumerate(amounts) if i % 5 != 0)
    manual_income = sum(a for i, a in enumerate(amounts) if i % 5 == 0)
    assert result.expense_minor == manual_expense
    assert result.income_minor == manual_income
    assert result.net_minor == manual_income - manual_expense


def test_reversal_offsets_original(account):
    original = _entry(
        account.id, amount=2000, when=NOW, key="rev-src"
    )
    reverse_entry(original.id, reason="错", idempotency_key="rev-1", now=NOW)
    period = Period.month(NOW, tz=TZ)
    result = summary(USER, period=period, compare_previous=False)
    assert result.expense_minor == 0
    assert result.income_minor == 0
    assert result.reversal_count == 1
    assert result.entry_count == 0


def test_transfer_excluded_from_expense(account):
    _entry(account.id, amount=1000, direction="expense", when=NOW, key="t1")
    _entry(account.id, amount=500, direction="transfer", when=NOW, key="t2")
    result = summary(USER, period=Period.month(NOW, tz=TZ), compare_previous=False)
    assert result.expense_minor == 1000
    assert result.transfer_minor == 500
    assert result.net_minor == -1000


def test_unclassified_bucket_present(account):
    categories = ledger_repository.list_categories(USER)
    cat = next(row for row in categories if row.name == "餐饮")
    _entry(account.id, amount=100, when=NOW, key="u1", category_id=None)
    _entry(account.id, amount=50, when=NOW, key="u2", category_id=cat.id)
    result = summary(USER, period=Period.month(NOW, tz=TZ), compare_previous=False)
    assert None in result.by_category
    assert result.by_category[None] == -100
    assert result.by_category[cat.id] == -50


def test_month_boundary_local_timezone(account):
    end_of_may = datetime(2026, 5, 31, 23, 59, 59, tzinfo=TZ)
    start_of_june = datetime(2026, 6, 1, 0, 0, 0, tzinfo=TZ)
    _entry(account.id, amount=111, when=end_of_may, key="may-end")
    _entry(account.id, amount=222, when=start_of_june, key="june-start")
    may = summary(
        USER,
        period=Period.month(datetime(2026, 5, 15, tzinfo=TZ), tz=TZ),
        compare_previous=False,
    )
    june = summary(
        USER,
        period=Period.month(NOW, tz=TZ),
        compare_previous=False,
    )
    assert may.expense_minor == 111
    assert june.expense_minor == 222


def test_period_is_half_open(account):
    until = datetime(2026, 6, 10, 0, 0, 0, tzinfo=TZ)
    _entry(account.id, amount=100, when=until, key="on-boundary")
    _entry(
        account.id,
        amount=200,
        when=until - timedelta(seconds=1),
        key="before-boundary",
    )
    period = Period.custom(
        datetime(2026, 6, 1, tzinfo=TZ), until, label="cutoff"
    )
    result = summary(USER, period=period, compare_previous=False)
    assert result.expense_minor == 200


def test_custom_period_compared_to_previous_equal_length(account):
    _entry(account.id, amount=100, when=NOW, key="cur")
    _entry(
        account.id,
        amount=50,
        when=NOW - timedelta(days=10),
        key="prev",
    )
    period = Period.custom(
        datetime(2026, 6, 10, tzinfo=TZ),
        datetime(2026, 6, 25, tzinfo=TZ),
        label="15d",
    )
    result = summary(USER, period=period, compare_previous=True)
    assert result.compared_to_previous is not None
    assert result.compared_to_previous.expense_delta == 100 - 50
    assert result.compared_to_previous.expense_ratio == pytest.approx(1.0)


def test_occurred_at_used_not_created_at(account, db_session_factory):
    from app.core.db import LedgerEntryRow

    entry = _entry(
        account.id,
        amount=300,
        when=datetime(2026, 5, 20, 12, 0, 0, tzinfo=TZ),
        key="backfill",
    )
    with db_session_factory() as session:
        row = session.get(LedgerEntryRow, entry.id)
        row.created_at = datetime(2026, 6, 2, 12, 0, 0)
        session.commit()
    may = summary(
        USER,
        period=Period.month(datetime(2026, 5, 15, tzinfo=TZ), tz=TZ),
        compare_previous=False,
    )
    june = summary(USER, period=Period.month(NOW, tz=TZ), compare_previous=False)
    assert may.expense_minor == 300
    assert june.expense_minor == 0


def test_entry_count_semantics(account):
    original = _entry(account.id, amount=100, when=NOW, key="ec1")
    _entry(account.id, amount=200, when=NOW, key="ec2")
    reverse_entry(original.id, reason="r", idempotency_key="ec-rev", now=NOW)
    result = summary(USER, period=Period.month(NOW, tz=TZ), compare_previous=False)
    assert result.entry_count == 1
    assert result.reversal_count == 1


def test_top_categories_ordering(account):
    categories = {
        row.name: row for row in ledger_repository.list_categories(USER)
    }
    for name, amount in (("餐饮", 500), ("交通", 300), ("娱乐", 900)):
        _entry(
            account.id,
            amount=amount,
            when=NOW,
            key=f"top-{name}",
            category_id=categories[name].id,
        )
    ranked = top_categories(USER, period=Period.month(NOW, tz=TZ), limit=2)
    assert len(ranked) == 2
    assert abs(ranked[0].net_minor) >= abs(ranked[1].net_minor)
    assert ranked[0].expense_minor == 900


def test_aggregation_is_read_only():
    source = (BACKEND / "app" / "services" / "ledger" / "query.py").read_text(
        encoding="utf-8"
    )
    assert "session.add" not in source
    assert "session.commit" not in source
    assert "create_entry" not in source


def test_aggregation_does_not_touch_llm():
    import ast

    source = (BACKEND / "app" / "services" / "ledger" / "query.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for banned in ("app.chains", "langchain", "app.prompts", "app.core.llm_factory"):
        assert not any(
            name == banned or name.startswith(banned + ".") for name in imported
        )
    assert "get_llm" not in source


def test_format_minor_exact():
    assert format_minor(3250) == "32.50"
    assert format_minor(5) == "0.05"
    assert format_minor(0) == "0.00"
    assert format_minor(-250) == "-2.50"


def test_entries_of_other_user_excluded(account):
    ensure_user_bootstrap("other-q", now=NOW.replace(tzinfo=None))
    other_account = ledger_repository.list_accounts("other-q")[0]
    _entry(account.id, amount=100, when=NOW, key="mine")
    record_entry(
        LedgerEntryDraft(
            user_id="other-q",
            account_id=other_account.id,
            amount_minor=999,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            idempotency_key="theirs",
        ),
        idempotency_key="theirs",
        now=NOW,
    )
    mine = summary(USER, period=Period.month(NOW, tz=TZ), compare_previous=False)
    theirs = summary(
        "other-q", period=Period.month(NOW, tz=TZ), compare_previous=False
    )
    assert mine.expense_minor == 100
    assert theirs.expense_minor == 999


def test_summary_after_full_write_path(account):
    original = _entry(account.id, amount=2000, when=NOW, key="e2e-1")
    reverse_entry(original.id, reason="r", idempotency_key="e2e-rev", now=NOW)
    _entry(account.id, amount=500, direction="income", when=NOW, key="e2e-2")
    result = summary(USER, period=Period.month(NOW, tz=TZ), compare_previous=False)
    assert result.expense_minor == 0
    assert result.income_minor == 500
    assert result.net_minor == 500


def test_query_surface_performance_baseline(account):
    import time

    base = datetime(2026, 6, 1, 8, 0, 0, tzinfo=TZ)
    for i in range(200):
        _entry(
            account.id,
            amount=10 + (i % 50),
            when=base + timedelta(minutes=i),
            key=f"perf-{i}",
        )
    started = time.perf_counter()
    result = summary(USER, period=Period.month(NOW, tz=TZ), compare_previous=True)
    elapsed = time.perf_counter() - started
    assert result.expense_minor > 0
    assert elapsed < 5.0


def test_trend_returns_periods(account):
    _entry(account.id, amount=100, when=NOW, key="tr1")
    periods = [
        Period.month(datetime(2026, 5, 1, tzinfo=TZ), tz=TZ),
        Period.month(NOW, tz=TZ),
    ]
    rows = trend(USER, periods=periods)
    assert len(rows) == 2
    assert rows[1].expense_minor == 100
