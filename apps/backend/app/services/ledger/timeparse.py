from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from app.core import timeutil

_NOON = ("中午", "午饭", "午餐")
_MORNING = ("早上", "上午", "今早", "早晨")
_EVENING = ("晚上", "傍晚", "今晚")
_NIGHT = ("昨晚", "夜里", "深夜")
_YESTERDAY = ("昨天", "昨日")
_TODAY = ("今天", "今日", "今晚", "今早")

_DAY_RE = re.compile(r"(?P<n>\d+)\s*天前")
_WEEKDAY_RE = re.compile(r"(?:上)?周(?P<day>[一二三四五六日天])")
_WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass(frozen=True, slots=True)
class TimeResolveResult:
    resolved: datetime | None
    confidence: float
    reason: str


def resolve_occurred_at(
    hint: str | None, *, world_time: datetime, timezone: str | None = None
) -> TimeResolveResult:
    if not hint:
        return TimeResolveResult(None, 0.0, "empty_hint")
    text = hint.strip()
    base = world_time
    if base.tzinfo is None:
        base = base.replace(tzinfo=timeutil.now().astimezone().tzinfo)

    day_offset = 0
    if any(token in text for token in _YESTERDAY):
        day_offset = -1
    elif any(token in text for token in _TODAY):
        day_offset = 0

    hour = None
    if any(token in text for token in _NOON):
        hour = 12
    elif any(token in text for token in _MORNING):
        hour = 8
    elif any(token in text for token in _NIGHT):
        hour = 21
        if any(token in text for token in _YESTERDAY) or "昨晚" in text:
            day_offset = -1
    elif any(token in text for token in _EVENING):
        hour = 19

    if "上周" in text or re.search(r"周[一二三四五六日天]", text):
        match = _WEEKDAY_RE.search(text)
        if match:
            target = _WEEKDAY_MAP[match.group("day")]
            current = timeutil.local(base).weekday()
            delta = current - target
            if "上周" in text:
                delta += 7
            if delta <= 0 and "上周" not in text:
                delta += 7
            resolved = (base - timedelta(days=delta)).replace(
                hour=hour if hour is not None else 12,
                minute=0,
                second=0,
                microsecond=0,
            )
            return TimeResolveResult(resolved, 0.8, "weekday")

    day_match = _DAY_RE.search(text)
    if day_match:
        day_offset = -int(day_match.group("n"))
        hour = hour if hour is not None else 12
        resolved = (base + timedelta(days=day_offset)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        return TimeResolveResult(resolved, 0.75, "days_ago")

    if hour is None:
        return TimeResolveResult(None, 0.0, "unparsable")

    resolved = (base + timedelta(days=day_offset)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )
    return TimeResolveResult(resolved, 0.85, "part_of_day")
