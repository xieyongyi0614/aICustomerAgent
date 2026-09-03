"""V9 时间短语解析（planner.md §1.2）。

扩展 V8 interpreter 既有"明天/后天/今晚"解析为共享模块；
解析失败返回 None（due 缺失进 missing_params，不猜时间）。
纯函数：显式注入 now。
"""

import re
from datetime import datetime, timedelta

_CN_DIGITS = {"零": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_WEEKDAY_CN = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6, "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6, "星期天": 6}

_RELATIVE_DELTAS = {
    "半小时": timedelta(minutes=30),
    "半个小时": timedelta(minutes=30),
    "一小时": timedelta(hours=1),
    "一个小时": timedelta(hours=1),
}

_MINUTES_PATTERN = re.compile(r"(半|\d+|[零一二两三四五六七八九十]+)分钟")


def _parse_cn_int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if all(ch in _CN_DIGITS for ch in text):
        return _CN_DIGITS.get(text)
    return None


def _parse_hour(text: str) -> int | None:
    return _parse_cn_int(text)


def _apply_daypart(base: datetime, phrase: str) -> datetime:
    if "凌晨" in phrase:
        base = base.replace(hour=6)
    if "早上" in phrase or "上午" in phrase or "早晨" in phrase:
        base = base.replace(hour=8)
    if "中午" in phrase:
        base = base.replace(hour=12)
    if "下午" in phrase:
        base = base.replace(hour=14)
    if "晚上" in phrase or "傍晚" in phrase:
        base = base.replace(hour=19)
    return base


def _apply_clock(base: datetime, text: str) -> datetime:
    match = re.search(
        r"(凌晨|早上|上午|中午|下午|晚上)?\s*(\d+|[零一二两三四五六七八九十]+)\s*(?:点|时|:：)?\s*(半|\d{1,2})?\s*分?",
        text,
    )
    if match is None or not _has_clock(text):
        return base
    hour = _parse_hour(match.group(2))
    if hour is None or not 0 <= hour <= 23:
        return base
    if match.group(1) in ("下午", "晚上") and hour < 12:
        hour += 12
    minute = 0
    if match.group(3) == "半":
        minute = 30
    elif match.group(3):
        minute = int(match.group(3))
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _has_clock(text: str) -> bool:
    return re.search(r"[点时:：]|点半|\d{1,2}半|[零一二两三四五六七八九十]+半", text) is not None


def parse_time_phrase(text: str, now: datetime) -> datetime | None:
    """时间短语 → due_at；无时间语义返回 None。"""
    if not text:
        return None

    for phrase, delta in _RELATIVE_DELTAS.items():
        if phrase in text:
            return (now + delta).replace(second=0, microsecond=0)

    minutes_match = _MINUTES_PATTERN.search(text)
    if minutes_match and ("后" in text[minutes_match.end():minutes_match.end() + 2] or "之后" in text):
        value = minutes_match.group(1)
        minutes = 30 if value == "半" else _parse_cn_int(value)
        if minutes is not None:
            return (now + timedelta(minutes=minutes)).replace(second=0, microsecond=0)

    for keyword, days in (("明天", 1), ("后天", 2), ("大后天", 3)):
        if keyword in text:
            base = (now + timedelta(days=days)).replace(hour=10, minute=0, second=0, microsecond=0)
            base = _apply_daypart(base, text)
            return _apply_clock(base, text)

    if "今晚" in text or ("今天" in text and "晚上" in text):
        return now.replace(hour=20, minute=0, second=0, microsecond=0)
    if "今晚" in text:
        return now.replace(hour=20, minute=0, second=0, microsecond=0)

    for keyword, weekday in _WEEKDAY_CN.items():
        if keyword in text:
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            base = (now + timedelta(days=days_ahead)).replace(hour=10, minute=0, second=0, microsecond=0)
            base = _apply_daypart(base, text)
            return _apply_clock(base, text)

    if "今天" in text or "现在" in text or "马上" in text or "立刻" in text:
        base = _apply_daypart(now.replace(second=0, microsecond=0), text)
        clock = _apply_clock(base, text)
        if clock != base or "点" in text:
            return clock
        return base

    if _has_clock(text):
        clock = _apply_clock(now.replace(hour=0, minute=0, second=0, microsecond=0), text)
        if clock.hour != 0 or "零点" in text:
            return clock

    for daypart in ("凌晨", "早上", "上午", "中午", "下午", "晚上", "傍晚"):
        if daypart in text:
            base = _apply_daypart(now.replace(second=0, microsecond=0), text)
            return _apply_clock(base, text)
    return None
