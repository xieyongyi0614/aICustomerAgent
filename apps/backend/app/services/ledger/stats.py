"""API-016 自动记账统计读面：只读聚合既有账目，零新数据源、零新表。

`accuracy`（分类准确率）与 `learned_from`（修正次数）在本期**刻意不出字段**：
`correction.py:51-117` 的订正产出只有「冲正行 + 新账行」，除冲正行 `note`（自由文本）
外没有任何「本次是否改了分类」的标记，全仓无修正计数落点（缺口 20 / 决策 D14）。
无真实来源的 KPI 一律不出现，禁止填 0 或估算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.services.ledger import category as category_service
from app.services.ledger import pending as pending_service
from app.services.ledger import query as query_service

AI_SOURCES: tuple[str, ...] = ("conversation", "action")


@dataclass(frozen=True, slots=True)
class AutoCategoryTotal:
    category_id: str | None
    category_name: str
    net_minor: int
    count: int


@dataclass(frozen=True, slots=True)
class AutoSummary:
    period: query_service.Period
    auto_count: int
    pending_count: int
    by_category: tuple[AutoCategoryTotal, ...]
    generated_at: datetime


def _signed(view) -> int:
    amount = int(view.amount_minor)
    if view.direction == "expense":
        return -amount
    if view.direction == "income":
        return amount
    return 0


def auto_summary(
    user_id: str, *, period: query_service.Period, now: datetime | None = None
) -> AutoSummary:
    timestamp = now or datetime.now()
    entries = [
        view
        for view in query_service.list_entries(user_id, period=period)
        if view.source in AI_SOURCES
    ]
    names = {
        row.id: row.name for row in category_service.list_user_categories(user_id)
    }
    net: dict[str | None, int] = {}
    counts: dict[str | None, int] = {}
    for view in entries:
        net[view.category_id] = net.get(view.category_id, 0) + _signed(view)
        counts[view.category_id] = counts.get(view.category_id, 0) + 1
    by_category = tuple(
        AutoCategoryTotal(
            category_id=key,
            category_name=names.get(key, "") if key else "",
            net_minor=value,
            count=counts[key],
        )
        for key, value in net.items()
    )
    return AutoSummary(
        period=period,
        auto_count=len(entries),
        pending_count=pending_service.list_pending(user_id, now=timestamp).total,
        by_category=by_category,
        generated_at=timestamp,
    )


__all__ = [
    "AI_SOURCES",
    "AutoCategoryTotal",
    "AutoSummary",
    "auto_summary",
]
