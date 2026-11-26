"""用户显式录入物品的抽取链（2026-10-10）。

默认家庭库存种子已移除：世界建档为空，物品只在**被显式要求记录**时创建。
本链把「用户明确要求记录物品」的自然语言转成结构化规格（含价格与购买时间）；
为避免每轮都付 LLM 成本，先用确定性前置闸 `has_record_intent` 过滤，未命中直接零调用。

金额口径：一律落**整数分**（`price_minor`），与账本域一致，零 float 落库。
购买时间归一为 ISO 日期（`purchased_at`），供 `models/world.py::usage_cost` 算日均。
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

from app.chains.structured import build_structured_chain
from app.core import timeutil
from app.models.world import WORLD_DB_CATEGORIES, ObjectIntake, ObjectIntakeItem
from app.prompts.object_intake import OBJECT_INTAKE_PROMPT
from app.services.ledger.timeparse import resolve_occurred_at

RECORD_INTENT_MARKERS = (
    "记一下",
    "帮我记",
    "记下来",
    "记录一下",
    "记上",
    "买了",
    "买点",
    "买个",
    "买回来",
    "家里有",
    "家里还有",
    "家里添",
    "冰箱里有",
    "冰箱里还有",
    "柜子里有",
    "库存",
    "囤了",
    "存了",
)

QUESTION_HINTS = ("什么", "吗", "呢", "？", "?", "几", "多少", "怎么", "哪", "有没有")


def has_record_intent(text: str) -> bool:
    """确定性前置闸：命中显式录入措辞才走 LLM 抽取（省成本、防误录）。

    问句（「冰箱里有什么」「还有几个鸡蛋」）不触发——那是**查询**，不是录入。
    """
    if any(hint in text for hint in QUESTION_HINTS):
        return False
    return any(marker in text for marker in RECORD_INTENT_MARKERS)


def build_object_intake_chain(llm=None):
    return build_structured_chain(
        [
            ("system", OBJECT_INTAKE_PROMPT),
            ("user", "用户消息：{user_input}"),
        ],
        ObjectIntake,
        llm,
    )


def _price_minor(price_yuan: float | None) -> int | None:
    """元 → 整数分；非正或缺失返回 None。"""
    if price_yuan is None or price_yuan <= 0:
        return None
    return round(price_yuan * 100)


BARE_DAY_OFFSETS = {"前天": 2, "昨天": 1, "昨日": 1, "今天": 0, "今日": 0}
_PERIOD_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?P<n>\d+)\s*天前"), "days"),
    (re.compile(r"(?P<n>\d+)\s*(?:个)?(?:周|星期)前"), "weeks"),
    (re.compile(r"(?P<n>\d+)\s*(?:个)?月前"), "months"),
)


def _minus_months(value: date, months: int) -> date:
    total = value.year * 12 + (value.month - 1) - months
    year, month = divmod(total, 12)
    day = min(value.day, calendar.monthrange(year, month + 1)[1])
    return date(year, month + 1, day)


def _relative_date(text: str, now: datetime) -> str | None:
    """购买日期兜底解析。

    `resolve_occurred_at` 只覆盖「带时段 / 星期几」的表达（账本语义需要具体时刻），
    裸的「昨天」「上个月」会判 unparsable；这里补上**日期粒度**的常见说法。
    """
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return datetime.fromisoformat(stripped).date().isoformat()
    except ValueError:
        pass
    base = timeutil.local(now).date()
    for word, offset in BARE_DAY_OFFSETS.items():
        if word in stripped:
            return (base - timedelta(days=offset)).isoformat()
    for pattern, unit in _PERIOD_PATTERNS:
        match = pattern.search(stripped)
        if not match:
            continue
        count = int(match.group("n"))
        if unit == "days":
            return (base - timedelta(days=count)).isoformat()
        if unit == "weeks":
            return (base - timedelta(days=7 * count)).isoformat()
        return _minus_months(base, count).isoformat()
    if "去年" in stripped:
        return _minus_months(base, 12).isoformat()
    if "上个月" in stripped or "上月" in stripped:
        return _minus_months(base, 1).isoformat()
    if "上周" in stripped:
        return (base - timedelta(days=7)).isoformat()
    return None


def _purchase_date(hint: str | None, now: datetime, *, has_price: bool) -> str | None:
    """购买时间归一为 ISO 日期。

    说了时间就解析（解析不出返回 None，**不编造**）；只说价格没说时间按「刚买」= 今天；
    两者都没有则 None（不参与日均计算）。
    """
    if hint:
        resolved = resolve_occurred_at(hint, world_time=now).resolved
        if resolved is not None:
            return resolved.date().isoformat()
        return _relative_date(hint, now)
    if has_price:
        return now.date().isoformat()
    return None


def extract_objects(
    message: str, *, now: datetime | None = None, llm=None
) -> ObjectIntake:
    """消息 → 录入意图（含归一后的 price_minor / purchased_at）。

    未命中意图或抽取异常一律返回空结果（宁缺毋滥）。
    """
    chain = build_object_intake_chain(llm)
    raw = chain.invoke({"user_input": message})
    if raw is None or not isinstance(raw, ObjectIntake) or not raw.is_record_intent:
        return ObjectIntake()

    moment = timeutil.ensure_aware(now) or timeutil.now()
    items: list[ObjectIntakeItem] = []
    for item in raw.items:
        name = (item.name or "").strip()
        if not name:
            continue
        category = item.category if item.category in WORLD_DB_CATEGORIES else "misc"
        quantity = item.quantity if item.quantity and item.quantity > 0 else 1.0
        price_minor = _price_minor(item.price_yuan)
        items.append(
            ObjectIntakeItem(
                name=name,
                category=category,
                quantity=quantity,
                unit=item.unit or "",
                price_yuan=item.price_yuan,
                purchased_at_hint=item.purchased_at_hint,
                price_minor=price_minor,
                purchased_at=_purchase_date(
                    item.purchased_at_hint, moment, has_price=price_minor is not None
                ),
            )
        )
    return ObjectIntake(
        is_record_intent=True, confidence=raw.confidence, items=tuple(items)
    )


__all__ = [
    "QUESTION_HINTS",
    "RECORD_INTENT_MARKERS",
    "build_object_intake_chain",
    "extract_objects",
    "has_record_intent",
]
