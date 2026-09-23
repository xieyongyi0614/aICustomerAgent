"""PLA-010 订正 / 冲正用例。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository
from app.services.ledger.correction import cancel_entry, revise_entry
from app.services.ledger.query import Period, summary
from app.services.ledger.service import (
    LedgerReversalError,
    ensure_user_bootstrap,
    record_entry,
)

NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "correction-user"


@pytest.fixture()
def bootstrapped(override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    account = ledger_repository.list_accounts(USER)[0]
    original = record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=account.id,
            amount_minor=2000,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            source_ref="src",
            idempotency_key="orig-1",
        ),
        idempotency_key="orig-1",
        now=NOW,
    ).entry
    return account, original


def _snapshot(entry):
    return (
        entry.id,
        entry.amount_minor,
        entry.direction,
        entry.category_id,
        entry.reversal_of,
        entry.idempotency_key,
        entry.note,
        entry.merchant,
    )


def test_revise_creates_reversal_and_new_entry(bootstrapped):
    account, original = bootstrapped
    outcome = revise_entry(
        original.id,
        {"amount_minor": 5000},
        reason="改金额",
        idempotency_key="rev-1",
        now=NOW,
    )
    assert outcome.original_entry_id == original.id
    assert outcome.reversal_entry_id
    assert outcome.new_entry_id
    assert ledger_repository.count_entries(USER) == 3


def test_revise_keeps_original_untouched(bootstrapped):
    account, original = bootstrapped
    before = _snapshot(original)
    revise_entry(
        original.id,
        {"amount_minor": 5000},
        reason="改金额",
        idempotency_key="rev-2",
        now=NOW,
    )
    after = _snapshot(ledger_repository.get_entry(original.id))
    assert after == before


def test_cancel_net_zero(bootstrapped):
    account, original = bootstrapped
    outcome = cancel_entry(
        original.id, reason="撤掉", idempotency_key="cancel-1", now=NOW
    )
    assert outcome.new_entry_id is None
    assert outcome.net_effect_minor == 0
    data = summary(USER, period=Period.month(NOW), now=NOW, compare_previous=False)
    assert data.expense_minor == 0
    assert data.income_minor == 0
    assert ledger_repository.get_entry(original.id) is not None


def test_revise_is_idempotent(bootstrapped):
    account, original = bootstrapped
    first = revise_entry(
        original.id,
        {"amount_minor": 5000},
        reason="改金额",
        idempotency_key="rev-3",
        now=NOW,
    )
    count = ledger_repository.count_entries(USER)
    second = revise_entry(
        original.id,
        {"amount_minor": 5000},
        reason="改金额",
        idempotency_key="rev-3",
        now=NOW,
    )
    assert ledger_repository.count_entries(USER) == count
    assert second.reversal_entry_id == first.reversal_entry_id


def test_cancel_is_idempotent(bootstrapped):
    account, original = bootstrapped
    first = cancel_entry(original.id, reason="撤", idempotency_key="cancel-2", now=NOW)
    count = ledger_repository.count_entries(USER)
    second = cancel_entry(original.id, reason="撤", idempotency_key="cancel-2", now=NOW)
    assert ledger_repository.count_entries(USER) == count
    assert second.reversal_entry_id == first.reversal_entry_id


def test_reversal_of_reversal_semantics(bootstrapped):
    """口径冻结：对冲正行再冲正 = 拒绝（append-only 不放宽）。"""
    account, original = bootstrapped
    outcome = cancel_entry(original.id, reason="撤", idempotency_key="cancel-3", now=NOW)
    with pytest.raises(LedgerReversalError):
        cancel_entry(
            outcome.reversal_entry_id,
            reason="再冲",
            idempotency_key="cancel-4",
            now=NOW,
        )


async def test_correction_goes_through_capability(bootstrapped, db_session_factory):
    account, original = bootstrapped
    from app.application import action_engine
    from app.models.action import ActionIntent, ActionPlan, ActionStep
    from app.repositories import action_repository
    from app.services.action.registry import ExecutionContext

    params = {
        "entry_id": original.id,
        "reason": "记错了",
        "idempotency_key": "cap-rev-1",
        "amount_minor": 3000,
    }
    intent = ActionIntent(
        action_type="revise_ledger_entry",
        confidence="confident",
        params=params,
        dedupe_key="dk-cap-rev",
    )
    record = action_engine.new_record(intent, USER, session_id=None)
    plan = ActionPlan(
        intent=intent,
        steps=[ActionStep(index=0, capability="ledger", action="revise", params=params)],
    )
    ctx = ExecutionContext(
        user_id=USER,
        record_id=record.id,
        now=NOW,
        settings=action_engine.get_settings(),
        dedupe_key=record.dedupe_key,
    )
    result = await action_engine.execute_plan(record, plan, ctx)
    assert result.status == "succeeded"
    saved = action_repository.get_record(record.id)
    assert saved is not None
    assert saved.status == "succeeded"


def test_corrected_amount_reflected_in_summary(bootstrapped):
    account, original = bootstrapped
    revise_entry(
        original.id,
        {"amount_minor": 5000},
        reason="改金额",
        idempotency_key="rev-sum",
        now=NOW,
    )
    data = summary(USER, period=Period.month(NOW), now=NOW, compare_previous=False)
    assert data.expense_minor == 5000


def test_correction_audited(bootstrapped):
    from app.services.governance.provenance import resolve_provenance

    account, original = bootstrapped
    outcome = cancel_entry(original.id, reason="撤", idempotency_key="audit-1", now=NOW)
    assert resolve_provenance("ledger", outcome.reversal_entry_id) is not None
