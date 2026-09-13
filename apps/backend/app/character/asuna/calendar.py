"""亚丝娜日历资产（V2.3.0 WS-005，architecture.md §5.2 CalendarAsset）。

季节为气象季节；节假日为公历近似值（中文语境常见节日），
年度细节调整属于遗留 Q6 的资产维护范畴。
"""

MONTH_SEASON = {
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
    12: "winter", 1: "winter", 2: "winter",
}

HOLIDAYS: dict[tuple[int, int], dict] = {
    (1, 1): {"name": "元旦", "kind": "festival"},
    (2, 14): {"name": "情人节", "kind": "festival"},
    (3, 8): {"name": "妇女节", "kind": "festival"},
    (4, 5): {"name": "清明", "kind": "memorial"},
    (5, 1): {"name": "劳动节", "kind": "festival"},
    (5, 4): {"name": "青年节", "kind": "festival"},
    (6, 1): {"name": "儿童节", "kind": "festival"},
    (9, 10): {"name": "教师节", "kind": "festival"},
    (10, 1): {"name": "国庆节", "kind": "festival"},
    (12, 24): {"name": "平安夜", "kind": "festival"},
    (12, 25): {"name": "圣诞节", "kind": "festival"},
}

SEASON_CN = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "winter": "冬",
}


def season_of(date_value) -> str:
    return MONTH_SEASON[date_value.month]


def holiday_of(date_value) -> dict | None:
    return HOLIDAYS.get((date_value.month, date_value.day))
