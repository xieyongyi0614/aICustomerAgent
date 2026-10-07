"""账本聚合：只从结构化字段求和，零 LLM、零写入口径。

期间（冻结）：
- 自然月：本地时区 [当月1日 00:00, 次月1日 00:00)
- 自然周：周一 00:00 起
- 自定义：[since, until) 左闭右开
- 归属时间恒用 occurred_at

entry_count（冻结）：有效条目数 = 总行数 − 冲正行数 − 被冲正的原条目数
  （原条目 + 其冲正对相抵后不计入有效条数）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Literal, Sequence
from zoneinfo import ZoneInfo

from app.core import timeutil
from app.models.ledger import to_major
from app.repositories import ledger_repository

GroupBy = Literal["category", "account", "direction"]


@dataclass(frozen=True, slots=True)
class Period:
    since: datetime
    until: datetime
    label: str = ""

    @staticmethod
    def custom(since: datetime, until: datetime, label: str = "") -> "Period":
        return Period(since=since, until=until, label=label or "custom")

    @staticmethod
    def month(anchor: datetime, *, tz: ZoneInfo | None = None) -> "Period":
        local = _localize(anchor, tz)
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return Period(since=start, until=end, label="month")

    @staticmethod
    def week(anchor: datetime, *, tz: ZoneInfo | None = None) -> "Period":
        local = _localize(anchor, tz)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = start - timedelta(days=start.weekday())
        return Period(since=start, until=start + timedelta(days=7), label="week")


@dataclass(frozen=True, slots=True)
class CategoryTotal:
    category_id: str | None
    net_minor: int
    expense_minor: int
    income_minor: int


@dataclass(frozen=True, slots=True)
class PeriodCompare:
    expense_delta: int
    income_delta: int
    expense_ratio: float | None


@dataclass(frozen=True, slots=True)
class LedgerSummary:
    period: Period
    expense_minor: int
    income_minor: int
    net_minor: int
    transfer_minor: int
    by_category: dict[str | None, int]
    by_account: dict[str, int]
    entry_count: int
    reversal_count: int
    compared_to_previous: PeriodCompare | None = None


@dataclass(frozen=True, slots=True)
class LedgerEntryView:
    id: str
    account_id: str
    category_id: str | None
    amount_minor: int
    currency: str
    direction: str
    occurred_at: datetime
    merchant: str | None
    note: str | None
    source: str
    source_ref: str | None
    idempotency_key: str
    reversal_of: str | None


def _localize(value: datetime, tz: ZoneInfo | None) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=tz or timeutil.now().astimezone().tzinfo)


def _net_by_key(
    pairs: Sequence[tuple[str | None, str, int]],
) -> dict[str | None, int]:
    net: dict[str | None, int] = {}
    for key, direction, total in pairs:
        current = net.get(key, 0)
        if direction == "expense":
            current -= total
        elif direction == "income":
            current += total
        net[key] = current
    return net


def _previous_equal_length(period: Period) -> Period:
    since = timeutil.ensure_aware(period.since)
    until = timeutil.ensure_aware(period.until)
    span = until - since
    return Period(
        since=period.since - span,
        until=period.since,
        label=f"previous:{period.label}" if period.label else "previous",
    )


def summary(
    user_id: str,
    *,
    period: Period,
    group_by: GroupBy | None = None,
    now: datetime | None = None,
    compare_previous: bool = True,
) -> LedgerSummary:
    expense, income, transfer = ledger_repository.sum_signed_minor(
        user_id, since=period.since, until=period.until
    )
    category_pairs = ledger_repository.sum_by_category(
        user_id, since=period.since, until=period.until
    )
    account_pairs = ledger_repository.sum_by_account(
        user_id, since=period.since, until=period.until
    )
    total, reversals, reversed_originals = ledger_repository.count_period_entries(
        user_id, since=period.since, until=period.until
    )
    entry_count = total - reversals - reversed_originals
    by_category = _net_by_key(category_pairs)
    by_account = {k: v for k, v in _net_by_key(account_pairs).items() if k is not None}

    compared = None
    if compare_previous:
        prev = _previous_equal_length(period)
        p_exp, p_inc, _ = ledger_repository.sum_signed_minor(
            user_id, since=prev.since, until=prev.until
        )
        ratio = None
        if p_exp:
            ratio = (expense - p_exp) / p_exp
        compared = PeriodCompare(
            expense_delta=expense - p_exp,
            income_delta=income - p_inc,
            expense_ratio=ratio,
        )

    return LedgerSummary(
        period=period,
        expense_minor=expense,
        income_minor=income,
        net_minor=income - expense,
        transfer_minor=transfer,
        by_category=by_category,
        by_account=by_account,
        entry_count=entry_count,
        reversal_count=reversals,
        compared_to_previous=compared,
    )


def trend(
    user_id: str, *, periods: Sequence[Period], now: datetime | None = None
) -> list[LedgerSummary]:
    return [
        summary(user_id, period=period, compare_previous=False) for period in periods
    ]


def daily_expense_series(
    user_id: str, *, days: int = 7, now: datetime | None = None
) -> list[int]:
    """近 N 天每日净支出（分，旧→新），口径同 `sum_signed_minor`：冲正按
    方向回冲（冲收入 = 回冲支出）；窗口内单次查询后按 `occurred_at` 当地日分桶，
    冲正落在其发生的当日，净额为负的日截 0（仅影响展示，不影响求和口径）。"""
    anchor = timeutil.ensure_aware(now) or timeutil.now()
    today = timeutil.local(anchor).date()
    first_day = today - timedelta(days=days - 1)
    # 边界必须是本地 aware：naive 会被当作库会话时区（UTC），首日 00:00–08:00
    # 的账目会被漏掉，柱状之和与区间合计就对不上。
    rows = ledger_repository.list_entries(
        user_id,
        since=timeutil.ensure_aware(datetime.combine(first_day, time.min)),
        until=timeutil.ensure_aware(
            datetime.combine(today + timedelta(days=1), time.min)
        ),
    )
    buckets = [0] * days
    for row in rows:
        offset = (timeutil.local(row.occurred_at).date() - first_day).days
        if offset < 0 or offset >= days:
            continue
        amount = int(row.amount_minor)
        if row.reversal_of is not None:
            if row.direction == "income":
                buckets[offset] -= amount
            continue
        if row.direction == "expense":
            buckets[offset] += amount
    return [max(0, value) for value in buckets]


def top_categories(
    user_id: str,
    *,
    period: Period,
    limit: int = 5,
    now: datetime | None = None,
) -> list[CategoryTotal]:
    pairs = ledger_repository.sum_by_category(
        user_id, since=period.since, until=period.until
    )
    expense: dict[str | None, int] = {}
    income: dict[str | None, int] = {}
    for category_id, direction, total in pairs:
        bucket = expense if direction == "expense" else income
        bucket[category_id] = bucket.get(category_id, 0) + total
    keys = set(expense) | set(income)
    totals = [
        CategoryTotal(
            category_id=key,
            net_minor=income.get(key, 0) - expense.get(key, 0),
            expense_minor=expense.get(key, 0),
            income_minor=income.get(key, 0),
        )
        for key in keys
    ]
    totals.sort(key=lambda item: (-abs(item.net_minor), item.category_id or ""))
    return totals[:limit]


def list_entries(
    user_id: str,
    *,
    period: Period | None = None,
    category_id: str | None = None,
    account_id: str | None = None,
    direction: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[LedgerEntryView]:
    rows = ledger_repository.list_entries(
        user_id,
        account_id=account_id,
        category_id=category_id,
        since=period.since if period else None,
        until=period.until if period else None,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return [
        LedgerEntryView(
            id=row.id,
            account_id=row.account_id,
            category_id=row.category_id,
            amount_minor=int(row.amount_minor),
            currency=row.currency,
            direction=row.direction,
            occurred_at=row.occurred_at,
            merchant=row.merchant,
            note=row.note,
            source=row.source,
            source_ref=row.source_ref,
            idempotency_key=row.idempotency_key,
            reversal_of=row.reversal_of,
        )
        for row in rows
    ]


def format_summary_amounts(summary_obj: LedgerSummary) -> dict[str, Any]:
    from app.services.ledger.format import format_minor

    return {
        "expense": format_minor(summary_obj.expense_minor),
        "income": format_minor(summary_obj.income_minor),
        "net": format_minor(summary_obj.net_minor),
    }
