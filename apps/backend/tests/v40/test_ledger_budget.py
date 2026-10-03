"""PLA-012 预算目标接入用例。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.core.db import GoalRow
from app.models.ledger import LedgerEntryDraft
from app.repositories import goal_repository, ledger_repository
from app.services.ledger import budget
from app.services.ledger.query import Period, summary
from app.services.ledger.service import ensure_user_bootstrap, record_entry, reverse_entry
from app.services.planning.goal_contract import BUDGET_CHECK_STEP

BACKEND = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 22, 12, 0, 0)
USER = "budget-user"


@pytest.fixture()
def setup(override_settings):
    override_settings()
    ensure_user_bootstrap(USER, now=NOW)
    return ledger_repository.list_accounts(USER)[0]


def _spec(**overrides) -> budget.BudgetSpec:
    base = {
        "user_id": USER,
        "scope": "total",
        "category_id": None,
        "period": "month",
        "limit_minor": 150000,
        "goal_id": "",
    }
    base.update(overrides)
    return budget.BudgetSpec(**base)


def _spend(account, amount=140000, key="s1", category_id=None):
    return record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=account.id,
            category_id=category_id,
            amount_minor=amount,
            direction="expense",
            occurred_at=NOW,
            source="manual",
            idempotency_key=key,
        ),
        idempotency_key=key,
        now=NOW,
    )


def test_upsert_budget_creates_goal(setup):
    spec = budget.upsert_budget(_spec(), now=NOW)
    assert spec.goal_id
    goal = goal_repository.get_goal(spec.goal_id)
    assert goal is not None
    assert goal.domain == "budget"
    assert goal.status == "active"


def test_upsert_budget_is_idempotent_by_scope_period(setup):
    first = budget.upsert_budget(_spec(), now=NOW)
    second = budget.upsert_budget(_spec(), now=NOW)
    assert second.goal_id == first.goal_id
    goals = goal_repository.list_layered_active(USER, domain="budget")
    assert len(goals) == 1


def test_list_budgets_projects_goal_to_spec(setup):
    created = budget.upsert_budget(_spec(limit_minor=150000), now=NOW)
    specs = budget.list_budgets(USER, period="month")
    assert len(specs) == 1
    assert specs[0].limit_minor == 150000
    assert specs[0].scope == "total"
    assert specs[0].goal_id == created.goal_id
    assert specs[0].currency == "CNY"


def test_archive_budget_sets_terminal_state(setup):
    created = budget.upsert_budget(_spec(), now=NOW)
    assert budget.archive_budget(created.goal_id, now=NOW) is True
    goal = goal_repository.get_goal(created.goal_id)
    assert goal.status == "abandoned"
    assert budget.list_budgets(USER) == []


def test_check_uses_summary_net_amount(setup):
    _spend(setup, amount=140000)
    spec = budget.upsert_budget(_spec(limit_minor=150000), now=NOW)
    check = budget.check_budget(USER, spec, now=NOW)
    data = summary(USER, period=Period.month(NOW), now=NOW, compare_previous=False)
    assert check.consumed_minor == data.expense_minor
    assert check.consumed_minor == 140000


def test_check_excludes_transfer(setup):
    record_entry(
        LedgerEntryDraft(
            user_id=USER,
            account_id=setup.id,
            amount_minor=50000,
            direction="transfer",
            occurred_at=NOW,
            source="manual",
            idempotency_key="t1",
        ),
        idempotency_key="t1",
        now=NOW,
    )
    _spend(setup, amount=1000, key="s2")
    spec = budget.upsert_budget(_spec(), now=NOW)
    check = budget.check_budget(USER, spec, now=NOW)
    assert check.consumed_minor == 1000


def test_check_reflects_reversal(setup):
    entry = _spend(setup, amount=50000, key="s3").entry
    reverse_entry(entry.id, reason="冲正", idempotency_key="rev-1", now=NOW)
    spec = budget.upsert_budget(_spec(), now=NOW)
    check = budget.check_budget(USER, spec, now=NOW)
    assert check.consumed_minor == 0


def test_breached_when_over_limit(setup):
    _spend(setup, amount=160000)
    spec = budget.upsert_budget(_spec(limit_minor=150000), now=NOW)
    check = budget.check_budget(USER, spec, now=NOW)
    assert check.breached is True
    assert check.reason == budget.REASON_OVER_LIMIT


def test_near_limit_ratio(setup):
    _spend(setup, amount=130000)  # 1300/1500 ≈ 0.867
    spec = budget.upsert_budget(_spec(limit_minor=150000), now=NOW)
    check = budget.check_budget(USER, spec, now=NOW)
    assert check.reason == budget.REASON_NEAR_LIMIT
    assert check.breached is True
    assert check.ratio >= budget.NEAR_LIMIT_RATIO


def test_no_data_period(override_settings):
    override_settings()
    ensure_user_bootstrap("empty-budget-user", now=NOW)
    spec = budget.upsert_budget(_spec(user_id="empty-budget-user"), now=NOW)
    check = budget.check_budget("empty-budget-user", spec, now=NOW)
    assert check.reason == budget.REASON_NO_DATA
    assert check.breached is False


def test_budget_write_only_via_goal_repository():
    source = (BACKEND / "app/services/ledger/budget.py").read_text(encoding="utf-8")
    assert "ledger_repository" not in source
    assert "create_entry" not in source
    assert "goal_repository" in source


def test_foreground_is_readonly():
    for name in ("chat_pipeline.py", "post_process.py"):
        source = (BACKEND / "app/application" / name).read_text(encoding="utf-8")
        assert "upsert_budget" not in source
        assert "create_goal" not in source


def test_budget_period_matches_ledger_period(setup):
    _spend(setup, amount=1000)
    spec = budget.upsert_budget(_spec(), now=NOW)
    check = budget.check_budget(USER, spec, now=NOW)
    assert check.consumed_minor == summary(
        USER, period=Period.month(NOW), now=NOW, compare_previous=False
    ).expense_minor


def test_no_new_columns_on_goals():
    columns = {column.name for column in GoalRow.__table__.columns}
    assert "limit_minor" not in columns
    assert "budget" not in columns
    assert {"id", "user_id", "domain", "origin", "layer", "status"} <= columns


def test_budget_check_step_registered():
    assert BUDGET_CHECK_STEP == "budget_check"
    from app.services.planning.goal_contract import PLANNING_STEP_TYPES

    assert "budget_check" in PLANNING_STEP_TYPES


def test_budget_check_runs_via_scheduler(setup):
    _spend(setup, amount=160000)
    budget.upsert_budget(_spec(limit_minor=150000), now=NOW)
    result = budget.run_budget_check_step(USER, now=NOW)
    assert result["step"] == "budget_check"
    assert result["breached"] >= 1


def test_over_budget_feeds_plan_observer(setup):
    _spend(setup, amount=160000)
    spec = budget.upsert_budget(_spec(limit_minor=150000), now=NOW)
    check = budget.check_budget(USER, spec, now=NOW)
    reason = budget.failure_reason_for(check)
    assert reason == "over_budget"


def test_planning_math_unchanged():
    planning_dir = BACKEND / "app/services/planning"
    targets = [
        planning_dir / "engine.py",
        planning_dir / "observer.py",
        planning_dir / "revision.py",
    ]
    targets.extend(sorted((planning_dir / "decompose").rglob("*.py")))
    for path in targets:
        source = path.read_text(encoding="utf-8")
        assert "budget.py" not in source, path.name
        assert "upsert_budget" not in source, path.name


def test_plan_write_surface_single(setup):
    source = (BACKEND / "app/services/ledger/budget.py").read_text(encoding="utf-8")
    assert source.count("goal_repository.") >= 2
    assert "SessionLocal" not in source
