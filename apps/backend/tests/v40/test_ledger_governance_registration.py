from __future__ import annotations

from datetime import datetime

from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.governance import delete_user_data, export_user_data, registered_domains
from app.services.ledger import ensure_user_bootstrap, record_entry

NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "gov-ledger-user"


def _seed():
    ensure_user_bootstrap(USER, now=NOW)
    account = ledger_repository.list_accounts(USER)[0]
    record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=account.id,
            amount_minor=1234,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            source_ref="m1",
            idempotency_key="gov-1",
        ),
        idempotency_key="gov-1",
        now=NOW,
    )


def test_ledger_domain_registered():
    import app.services.ledger.service  # noqa: F401

    assert "ledger" in registered_domains()


def test_export_covers_ledger():
    _seed()
    bundle = export_user_data(USER)
    payload = bundle.domains["ledger"]
    assert len(payload["accounts"]) == len(
        ledger_repository.list_accounts(USER, include_archived=True)
    )
    assert len(payload["categories"]) == len(ledger_repository.list_categories(USER))
    assert len(payload["entries"]) == len(ledger_repository.list_entries(USER))


def test_delete_ledger_zero_residue():
    _seed()
    report = delete_user_data(USER)
    assert report.per_domain["ledger"] >= 3
    assert ledger_repository.count_entries(USER) == 0
    assert ledger_repository.list_categories(USER) == []
    assert ledger_repository.list_accounts(USER, include_archived=True) == []


def test_delete_uses_repository_surface(monkeypatch):
    _seed()
    calls = []
    for name in (
        "delete_entries_for_user",
        "delete_categories_for_user",
        "delete_accounts_for_user",
    ):
        original = getattr(ledger_repository, name)

        def wrapper(fn=name, orig=original):
            def _call(user_id: str):
                calls.append(fn)
                return orig(user_id)

            return _call

        monkeypatch.setattr(ledger_repository, name, wrapper())
    delete_user_data(USER)
    assert calls == [
        "delete_entries_for_user",
        "delete_categories_for_user",
        "delete_accounts_for_user",
    ]


def test_export_does_not_leak_amount_to_prompt(monkeypatch):
    _seed()
    called = []
    from app.services.governance import prompt_guard

    monkeypatch.setattr(
        prompt_guard,
        "assert_no_financial_detail",
        lambda text: called.append(text) or text,
    )
    export_user_data(USER)
    assert called == []
