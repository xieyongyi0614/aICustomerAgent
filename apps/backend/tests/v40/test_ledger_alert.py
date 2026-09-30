"""PLA-013 超支预警用例。"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.channels.base import ChannelErrorKind, SendResult
from app.core.settings import get_settings
from app.models.ledger import LedgerEntryDraft
from app.repositories import ledger_repository, proactive_repository
from app.services.ledger import alert, budget
from app.services.ledger.format import format_minor
from app.services.ledger.query import Period, summary
from app.services.ledger.service import ensure_user_bootstrap, record_entry, reverse_entry

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "alert-user"


@pytest.fixture()
def setup(override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    return ledger_repository.list_accounts(USER)[0]


def _spec(limit_minor=10000) -> budget.BudgetSpec:
    return budget.BudgetSpec(
        user_id=USER,
        scope="total",
        category_id=None,
        period="month",
        limit_minor=limit_minor,
        goal_id="",
    )


def _spend(account, amount, key="a1"):
    return record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=account.id,
            amount_minor=amount,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            idempotency_key=key,
        ),
        idempotency_key=key,
        now=NOW,
    )


def test_budget_over_triggers_alert(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    drafts = alert.evaluate_alerts(USER, now=NOW)
    kinds = {d.kind for d in drafts}
    assert alert.KIND_BUDGET_OVER in kinds


def test_budget_near_triggers_alert(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=9000)
    drafts = alert.evaluate_alerts(USER, now=NOW)
    kinds = {d.kind for d in drafts}
    assert alert.KIND_BUDGET_NEAR in kinds
    assert alert.KIND_BUDGET_OVER not in kinds


def test_budget_ok_no_alert(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=1000)
    drafts = [d for d in alert.evaluate_alerts(USER, now=NOW) if d.kind.startswith("budget")]
    assert drafts == []


def test_dedupes_within_same_period(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    delivered = 0
    for _ in range(5):
        for draft in alert.evaluate_alerts(USER, now=NOW):
            if alert.should_alert(draft, now=NOW) and alert.deliver_alert(
                draft, now=NOW, user_id=USER
            ).ok:
                delivered += 1
    assert delivered == 1


def test_new_period_resets_dedupe(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    first = alert.evaluate_alerts(USER, now=NOW)[0]
    alert.deliver_alert(first, now=NOW, user_id=USER)
    next_month = datetime(2026, 10, 22, 12, 0, 0)
    budget.upsert_budget(_spec(limit_minor=10000), now=next_month)
    record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=setup.id,
            amount_minor=12000,
            direction="expense",
            occurred_at=next_month,
            source="manual",
            idempotency_key="a-next",
        ),
        idempotency_key="a-next",
        now=next_month,
    )
    drafts = alert.evaluate_alerts(USER, now=next_month)
    assert drafts
    assert drafts[0].dedupe_key != first.dedupe_key
    assert alert.should_alert(drafts[0], now=next_month) is True


def test_quiet_hours_skip_no_catchup(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    draft = alert.evaluate_alerts(USER, now=NOW)[0]
    quiet = NOW.replace(hour=23, minute=30)
    assert alert.should_alert(draft, now=quiet) is False


def test_no_data_does_not_alert(override_settings):
    override_settings()
    ensure_user_bootstrap("empty-alert", now=NOW)
    assert alert.evaluate_alerts("empty-alert", now=NOW) == []


def test_daily_spike_requires_absolute_floor(override_settings):
    override_settings()
    ensure_user_bootstrap("spike-user", now=NOW)
    account = ledger_repository.list_accounts("spike-user")[0]
    day_start = NOW.replace(hour=0, minute=0, second=0, microsecond=0)
    for offset in range(1, 4):
        record_entry(
            LedgerEntryDraft(
                user_id="spike-user",
                account_id=account.id,
                amount_minor=300,
                direction="expense",
                occurred_at=day_start - timedelta(days=offset),
                source="manual",
                idempotency_key=f"base-{offset}",
            ),
            idempotency_key=f"base-{offset}",
            now=NOW,
        )
    record_entry(
        LedgerEntryDraft(
            user_id="spike-user",
            account_id=account.id,
            amount_minor=1000,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            idempotency_key="spike-1",
        ),
        idempotency_key="spike-1",
        now=NOW,
    )
    drafts = alert.evaluate_alerts("spike-user", now=NOW)
    assert all(d.kind != alert.KIND_DAILY_SPIKE for d in drafts)


def test_monthly_surge_threshold(setup):
    prev_start = datetime(2026, 8, 1)
    for i, amount in enumerate((30000, 30000)):
        record_entry(
            LedgerEntryDraft(
                user_id=USER,
                account_id=setup.id,
                amount_minor=amount,
                direction="expense",
                occurred_at=prev_start + timedelta(days=i + 1),
                source="manual",
                idempotency_key=f"prev-{i}",
            ),
            idempotency_key=f"prev-{i}",
            now=NOW,
        )
    _spend(setup, amount=100000, key="this-1")
    drafts = alert.evaluate_alerts(USER, now=NOW)
    kinds = {d.kind for d in drafts}
    assert alert.KIND_MONTHLY_SURGE in kinds


def test_alert_numbers_match_aggregation(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    draft = next(d for d in alert.evaluate_alerts(USER, now=NOW) if d.kind == alert.KIND_BUDGET_OVER)
    data = summary(USER, period=Period.month(NOW), now=NOW, compare_previous=False)
    assert format_minor(data.expense_minor) in draft.body
    assert draft.observed["consumed_minor"] == data.expense_minor


def test_alert_reflects_reversal(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    entry = _spend(setup, amount=12000).entry
    assert any(d.kind == alert.KIND_BUDGET_OVER for d in alert.evaluate_alerts(USER, now=NOW))
    reverse_entry(entry.id, reason="冲正", idempotency_key="arev-1", now=NOW)
    drafts = alert.evaluate_alerts(USER, now=NOW)
    assert all(d.kind != alert.KIND_BUDGET_OVER for d in drafts)


def test_alert_module_has_no_llm_import():
    source = (BACKEND / "app/services/ledger/alert.py").read_text(encoding="utf-8")
    for forbidden in ("chains", "llm_factory", "ChatOpenAI", "langchain", "get_llm"):
        assert forbidden not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "llm" not in node.module.lower()
            assert "chain" not in node.module.lower()


def test_alert_templates_placeholder_only(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    draft = alert.evaluate_alerts(USER, now=NOW)[0]
    for word in ("约", "大概", "可能", "应该"):
        assert word not in draft.body


def test_deliver_failure_does_not_raise(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    draft = alert.evaluate_alerts(USER, now=NOW)[0]

    class Boom:
        async def send(self, *args, **kwargs):
            raise RuntimeError("boom")

    from app.services.delivery import outbound as proactive_delivery

    proactive_delivery.register_proactive_outbound(
        proactive_delivery.ProactiveOutbound(channel="web", send=Boom().send)
    )
    try:
        result = alert.deliver_alert(draft, now=NOW, user_id=USER)
        assert result.ok is False
    finally:
        proactive_delivery.reset_proactive_outbound()


def test_alert_records_proactive_action(setup):
    budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
    _spend(setup, amount=12000)
    draft = alert.evaluate_alerts(USER, now=NOW)[0]
    alert.deliver_alert(draft, now=NOW, user_id=USER)
    rows = proactive_repository.list_since(NOW - timedelta(minutes=1))
    assert any(row.dedupe_key == draft.dedupe_key for row in rows)
    assert draft.dedupe_key.startswith(f"ledger_alert:{draft.kind}:")


def test_alert_trigger_registered():
    assert alert.ALERT_TRIGGER_SOURCE == "ledger_alert"
    source = (BACKEND / "app/application/life_loop.py").read_text(encoding="utf-8")
    assert '_mark_maintenance("ledger_alert")' in source


def test_evaluation_runs_in_background_cycle():
    source = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "ledger_alert" not in source
    source_loop = (BACKEND / "app/application/life_loop.py").read_text(encoding="utf-8")
    assert "ledger_alert" in source_loop


def test_delivery_goes_through_outbound_gateway(setup):
    from app.services.delivery import outbound as proactive_delivery

    calls = []

    async def send(user_id, text, dedupe_key):
        calls.append(dedupe_key)
        return SendResult(ok=True, external_message_id="om-1")

    proactive_delivery.register_proactive_outbound(
        proactive_delivery.ProactiveOutbound(channel="web", send=send)
    )
    try:
        budget.upsert_budget(_spec(limit_minor=10000), now=NOW)
        _spend(setup, amount=12000)
        draft = alert.evaluate_alerts(USER, now=NOW)[0]
        result = alert.deliver_alert(draft, now=NOW, user_id=USER)
        assert result.ok is True
        assert calls == [draft.dedupe_key]
    finally:
        proactive_delivery.reset_proactive_outbound()


def test_trigger_evaluation_math_unchanged():
    for name in ("autonomy_policy.py", "trigger_evaluator.py"):
        path = BACKEND / "app/services" / name
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "alert.py" not in source
        assert "evaluate_alerts" not in source
