"""PLA-014 消费洞察：特征投影不含金额（类型层零金额保证）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from app.services.ledger.query import Period, list_entries, summary, top_categories

LATE_NIGHT_HOUR = 22


@dataclass(frozen=True, slots=True)
class SpendingFeatures:
    period_label: str
    top_category_share: Mapping[str, float]
    late_night_ratio: float
    unclassified_ratio: float
    frequency_by_category: Mapping[str, int]
    weekday_vs_weekend_ratio: float
    entry_count: int
    reversal_count: int


def project_features(
    user_id: str, *, now: datetime | None = None, period: Period | None = None
) -> SpendingFeatures | None:
    timestamp = now or datetime.now()
    window = period or Period.month(timestamp)
    data = summary(user_id, period=window, now=timestamp, compare_previous=False)
    if data.entry_count <= 0:
        return None
    entries = list_entries(user_id, period=window, limit=500)
    total_abs = sum(abs(int(item.amount_minor)) for item in entries) or 1
    category_abs: dict[str | None, int] = {}
    category_count: dict[str | None, int] = {}
    late = 0
    weekday = 0
    weekend = 0
    for item in entries:
        category_abs[item.category_id] = category_abs.get(item.category_id, 0) + abs(
            int(item.amount_minor)
        )
        category_count[item.category_id] = category_count.get(item.category_id, 0) + 1
        if item.occurred_at.hour >= LATE_NIGHT_HOUR or item.occurred_at.hour < 5:
            late += 1
        if item.occurred_at.weekday() >= 5:
            weekend += 1
        else:
            weekday += 1
    unclassified = category_abs.get(None, 0)
    share = {
        (key or "未归类"): value / total_abs for key, value in category_abs.items()
    }
    frequency = {(key or "未归类"): value for key, value in category_count.items()}
    denom = weekday + weekend or 1
    return SpendingFeatures(
        period_label=window.label or "custom",
        top_category_share=dict(share),
        late_night_ratio=late / max(len(entries), 1),
        unclassified_ratio=unclassified / total_abs,
        frequency_by_category=dict(frequency),
        weekday_vs_weekend_ratio=weekday / denom,
        entry_count=data.entry_count,
        reversal_count=data.reversal_count,
    )


def feature_summary_text(features: SpendingFeatures) -> str:
    """证据摘要：只含比率 / 次数，不含金额。"""
    top = sorted(features.top_category_share.items(), key=lambda item: -item[1])[:3]
    top_text = "、".join(f"{name}占比{share:.0%}" for name, share in top) if top else "无"
    return (
        f"期间{features.period_label}：类目分布 {top_text}；"
        f"夜间占比{features.late_night_ratio:.0%}；"
        f"未归类占比{features.unclassified_ratio:.0%}；"
        f"条目{features.entry_count}笔冲正{features.reversal_count}笔"
    )


def derive_pattern_statements(features: SpendingFeatures) -> list[str]:
    """确定性模式候选（零 LLM）：只描述模式，不给建议、不含金额。"""
    statements: list[str] = []
    top = sorted(features.top_category_share.items(), key=lambda item: -item[1])
    if top and top[0][1] >= 0.4:
        statements.append(f"消费高度集中在{top[0][0]}")
    if features.late_night_ratio >= 0.3:
        statements.append("夜间消费占比偏高")
    if features.unclassified_ratio >= 0.3:
        statements.append("未归类消费偏多")
    freq = sorted(features.frequency_by_category.items(), key=lambda item: -item[1])
    if freq and freq[0][1] >= 5:
        statements.append(f"{freq[0][0]}出现频次较高")
    return statements


__all__ = [
    "SpendingFeatures",
    "derive_pattern_statements",
    "feature_summary_text",
    "project_features",
]
