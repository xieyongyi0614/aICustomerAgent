"""PLA-012 预算 = goal 的领域视图（零新表、零新列；写只经 goal_repository）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core import timeutil
from app.repositories import goal_repository
from app.services.ledger.query import Period, summary

BUDGET_DOMAIN = "budget"
NEAR_LIMIT_RATIO = 0.8
REASON_OK = "ok"
REASON_OVER_LIMIT = "over_limit"
REASON_NEAR_LIMIT = "near_limit"
REASON_NO_DATA = "no_data"

ORIGIN_PREFIX = "user:budget"


@dataclass(frozen=True, slots=True)
class BudgetSpec:
    user_id: str
    scope: str
    category_id: str | None
    period: str
    limit_minor: int
    goal_id: str
    currency: str = "CNY"


@dataclass(frozen=True, slots=True)
class BudgetCheck:
    budget: BudgetSpec
    consumed_minor: int
    remaining_minor: int
    ratio: float
    breached: bool
    reason: str


def _origin(spec: BudgetSpec) -> str:
    category = spec.category_id or "total"
    return (
        f"{ORIGIN_PREFIX}:{spec.scope}:{category}:{spec.period}:"
        f"{spec.limit_minor}:{spec.currency}"
    )


def _description(spec: BudgetSpec) -> str:
    label = spec.category_id or "total"
    return f"预算{label}{spec.period}{spec.limit_minor}"[:40]


def _parse_origin(origin: str) -> tuple[str, str | None, str, int, str] | None:
    if not origin or not origin.startswith(ORIGIN_PREFIX + ":"):
        return None
    parts = origin.split(":")
    # user:budget:scope:category:period:limit:currency
    if len(parts) != 7:
        return None
    _user, _budget, scope, category, period, limit_text, currency = parts
    try:
        limit_minor = int(limit_text)
    except ValueError:
        return None
    category_id = None if category == "total" else category
    return scope, category_id, period, limit_minor, currency


def _project(goal) -> BudgetSpec | None:
    parsed = _parse_origin(goal.origin or "")
    if parsed is None:
        return None
    scope, category_id, period, limit_minor, currency = parsed
    return BudgetSpec(
        user_id=goal.user_id,
        scope=scope,
        category_id=category_id,
        period=period,
        limit_minor=limit_minor,
        goal_id=goal.id,
        currency=currency,
    )


def list_budgets(user_id: str, *, period: str | None = None) -> list[BudgetSpec]:
    goals = goal_repository.list_layered_active(user_id, domain=BUDGET_DOMAIN)
    specs = [item for item in (_project(goal) for goal in goals) if item is not None]
    if period is not None:
        specs = [item for item in specs if item.period == period]
    return specs


def upsert_budget(spec: BudgetSpec, *, now: datetime | None = None) -> BudgetSpec:
    """写入只经 goal_repository 计划面；同 scope+period+category 幂等更新。"""
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    existing = next(
        (
            item
            for item in list_budgets(spec.user_id, period=spec.period)
            if item.scope == spec.scope
            and item.category_id == spec.category_id
            and item.period == spec.period
        ),
        None,
    )
    if existing is not None and existing.limit_minor == spec.limit_minor:
        return existing
    if existing is not None:
        goal_repository.finish_goal(existing.goal_id, "abandoned")
    from app.models.goal import GoalRecord

    goal = goal_repository.create_goal(
        GoalRecord(
            user_id=spec.user_id,
            type="user_care",
            description=_description(spec),
            priority=3,
            status="active",
            horizon="current",
            source="definition",
            created_at=timestamp,
            updated_at=timestamp,
            layer="short_term",
            domain=BUDGET_DOMAIN,
            origin=_origin(spec),
        )
    )
    return BudgetSpec(
        user_id=spec.user_id,
        scope=spec.scope,
        category_id=spec.category_id,
        period=spec.period,
        limit_minor=spec.limit_minor,
        goal_id=goal.id,
        currency=spec.currency,
    )


def archive_budget(goal_id: str, *, now: datetime | None = None) -> bool:
    result = goal_repository.finish_goal(goal_id, "abandoned")
    return result is not None and result.status == "abandoned"


def _period_for(period_name: str, now: datetime) -> Period:
    if period_name == "week":
        return Period.week(now)
    return Period.month(now)


def check_budget(
    user_id: str, spec: BudgetSpec, *, now: datetime | None = None
) -> BudgetCheck:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
    period = _period_for(spec.period, timestamp)
    data = summary(user_id, period=period, now=timestamp, compare_previous=False)
    if spec.scope == "category" and spec.category_id:
        net = data.by_category.get(spec.category_id, 0)
        consumed = max(0, -int(net))
    else:
        consumed = int(data.expense_minor)
    remaining = spec.limit_minor - consumed
    ratio = (consumed / spec.limit_minor) if spec.limit_minor else 0.0
    if data.entry_count <= 0:
        reason = REASON_NO_DATA
        breached = False
    elif consumed > spec.limit_minor:
        reason = REASON_OVER_LIMIT
        breached = True
    elif ratio >= NEAR_LIMIT_RATIO:
        reason = REASON_NEAR_LIMIT
        breached = True
    else:
        reason = REASON_OK
        breached = False
    return BudgetCheck(
        budget=spec,
        consumed_minor=consumed,
        remaining_minor=remaining,
        ratio=ratio,
        breached=breached,
        reason=reason,
    )


def check_all_budgets(
    user_id: str, *, now: datetime | None = None, period: str | None = "month"
) -> list[BudgetCheck]:
    return [
        check_budget(user_id, spec, now=now)
        for spec in list_budgets(user_id, period=period)
    ]


def failure_reason_for(check: BudgetCheck) -> str | None:
    from app.services.planning.goal_contract import (
        PLANNING_FAILURE_REASON_BUDGET_EXHAUSTED,
        PLANNING_FAILURE_REASON_OVER_BUDGET,
    )

    if check.reason == REASON_OVER_LIMIT:
        return PLANNING_FAILURE_REASON_OVER_BUDGET
    if check.reason == REASON_NEAR_LIMIT and check.remaining_minor <= 0:
        return PLANNING_FAILURE_REASON_BUDGET_EXHAUSTED
    return None


def run_budget_check_step(user_id: str, *, now: datetime | None = None) -> dict:
    checks = check_all_budgets(user_id, now=now)
    breached = [check for check in checks if check.breached]
    return {
        "step": "budget_check",
        "status": "ok",
        "checked": len(checks),
        "breached": len(breached),
        "reasons": [failure_reason_for(check) or check.reason for check in breached],
    }


__all__ = [
    "BUDGET_DOMAIN",
    "BudgetCheck",
    "BudgetSpec",
    "NEAR_LIMIT_RATIO",
    "archive_budget",
    "check_all_budgets",
    "check_budget",
    "failure_reason_for",
    "list_budgets",
    "run_budget_check_step",
    "upsert_budget",
]
