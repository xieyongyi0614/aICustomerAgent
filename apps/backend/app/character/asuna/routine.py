"""亚丝娜日常作息资产（V2.3.0 WS-007，architecture.md §5.3 RoutineAsset）。

按日型 × part 的活动块模板；变体块加权随机由 DailyPlanBuilder 种子驱动；
时间边界与既有 part_of_day 词表（morning/afternoon/dusk/evening/late_night）对齐。
内容变更须递增 ROUTINE_VERSION（计划可复现性依赖它）。
"""

ROUTINE_VERSION = 1

DAY_TYPES = ("weekday", "weekend", "holiday")

ROUTINE_TEMPLATES: dict[str, list[dict]] = {
    "weekday": [
        {
            "seq": 0, "part": "morning", "start_min": 390, "end_min": 450,
            "activity": "做早餐", "location_id": "home.kitchen",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["早餐", "家常"],
        },
        {
            "seq": 1, "part": "morning", "start_min": 450, "end_min": 480,
            "activity": "收拾准备", "location_id": "home.living_room",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 0, "topics": ["日常"],
        },
        {
            "seq": 2, "part": "morning", "start_min": 480, "end_min": 660,
            "activity": "工作学习", "location_id": "company.workstation",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "工作", "location_id": "company.workstation", "weight": 3},
                    {"activity": "上课学习", "location_id": "school.classroom", "weight": 1},
                ],
            },
            "user_influencable": False, "energy_bias": 0, "topics": ["工作", "学习"],
        },
        {
            "seq": 3, "part": "afternoon", "start_min": 660, "end_min": 780,
            "activity": "午餐小憩", "location_id": "home.dining_area",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["午餐"],
        },
        {
            "seq": 4, "part": "afternoon", "start_min": 780, "end_min": 840,
            "activity": "下午茶", "location_id": "cafe.main",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "咖啡店下午茶", "location_id": "cafe.main", "weight": 2},
                    {"activity": "在家休息", "location_id": "home.living_room", "weight": 3},
                ],
            },
            "user_influencable": False, "energy_bias": 1, "topics": ["咖啡", "闲聊"],
        },
        {
            "seq": 5, "part": "dusk", "start_min": 840, "end_min": 1020,
            "activity": "下午工作学习", "location_id": "company.workstation",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 0, "topics": ["工作", "学习"],
        },
        {
            "seq": 6, "part": "dusk", "start_min": 1020, "end_min": 1080,
            "activity": "傍晚散步", "location_id": "park.path",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "公园散步", "location_id": "park.path", "weight": 2},
                    {"activity": "在家休息", "location_id": "home.living_room", "weight": 2},
                ],
            },
            "user_influencable": False, "energy_bias": 1, "topics": ["散步", "见闻"],
        },
        {
            "seq": 7, "part": "evening", "start_min": 1080, "end_min": 1200,
            "activity": "做晚餐", "location_id": "home.kitchen",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["晚餐", "家常"],
        },
        {
            "seq": 8, "part": "evening", "start_min": 1200, "end_min": 1320,
            "activity": "兴趣时间", "location_id": "home.living_room",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "阅读", "location_id": "home.living_room", "weight": 3},
                    {"activity": "追剧", "location_id": "home.living_room", "weight": 2},
                    {"activity": "运动", "location_id": "school.playground", "weight": 1},
                ],
            },
            "user_influencable": True, "energy_bias": 1, "topics": ["兴趣", "分享"],
        },
        {
            "seq": 9, "part": "late_night", "start_min": 1320, "end_min": 1380,
            "activity": "洗漱放松", "location_id": "home.bathroom",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": -1, "topics": ["日常"],
        },
        {
            "seq": 10, "part": "late_night", "start_min": 1380, "end_min": 1430,
            "activity": "休息", "location_id": "home.bedroom",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": -2, "topics": ["晚安"],
        },
    ],
    "weekend": [
        {
            "seq": 0, "part": "morning", "start_min": 450, "end_min": 510,
            "activity": "慢起早餐", "location_id": "home.dining_area",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["早餐", "周末"],
        },
        {
            "seq": 1, "part": "morning", "start_min": 510, "end_min": 660,
            "activity": "收拾打扫", "location_id": "home.living_room",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "打扫房间", "location_id": "home.living_room", "weight": 2},
                    {"activity": "阳台晾晒", "location_id": "home.balcony", "weight": 2},
                ],
            },
            "user_influencable": False, "energy_bias": 0, "topics": ["家务"],
        },
        {
            "seq": 2, "part": "afternoon", "start_min": 660, "end_min": 780,
            "activity": "午餐", "location_id": "home.dining_area",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["午餐"],
        },
        {
            "seq": 3, "part": "afternoon", "start_min": 780, "end_min": 960,
            "activity": "外出活动", "location_id": "cafe.main",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "咖啡店坐坐", "location_id": "cafe.main", "weight": 2},
                    {"activity": "公园走走", "location_id": "park.path", "weight": 2},
                    {"activity": "图书馆看书", "location_id": "school.library", "weight": 1},
                ],
            },
            "user_influencable": True, "energy_bias": 1, "topics": ["外出", "见闻"],
        },
        {
            "seq": 4, "part": "dusk", "start_min": 960, "end_min": 1080,
            "activity": "自由时光", "location_id": "home.living_room",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 0, "topics": ["兴趣"],
        },
        {
            "seq": 5, "part": "evening", "start_min": 1080, "end_min": 1200,
            "activity": "晚餐", "location_id": "home.dining_area",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["晚餐"],
        },
        {
            "seq": 6, "part": "evening", "start_min": 1200, "end_min": 1320,
            "activity": "晚间消遣", "location_id": "home.living_room",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "追剧", "location_id": "home.living_room", "weight": 2},
                    {"activity": "打游戏", "location_id": "home.living_room", "weight": 2},
                ],
            },
            "user_influencable": True, "energy_bias": 1, "topics": ["娱乐", "分享"],
        },
        {
            "seq": 7, "part": "late_night", "start_min": 1320, "end_min": 1430,
            "activity": "休息", "location_id": "home.bedroom",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": -2, "topics": ["晚安"],
        },
    ],
    "holiday": [
        {
            "seq": 0, "part": "morning", "start_min": 480, "end_min": 540,
            "activity": "节日早餐", "location_id": "home.dining_area",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["节日", "早餐"],
        },
        {
            "seq": 1, "part": "afternoon", "start_min": 600, "end_min": 900,
            "activity": "节日外出", "location_id": "park.path",
            "variability": {
                "mode": "variant",
                "alternatives": [
                    {"activity": "逛节日集市", "location_id": "park.path", "weight": 2},
                    {"activity": "咖啡店小坐", "location_id": "cafe.main", "weight": 2},
                    {"activity": "海边走走", "location_id": "travel_seaside", "weight": 1},
                ],
            },
            "user_influencable": True, "energy_bias": 2, "topics": ["节日", "外出"],
        },
        {
            "seq": 2, "part": "dusk", "start_min": 900, "end_min": 1080,
            "activity": "休整", "location_id": "home.living_room",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 0, "topics": ["日常"],
        },
        {
            "seq": 3, "part": "evening", "start_min": 1080, "end_min": 1260,
            "activity": "节日晚餐", "location_id": "home.dining_area",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": 1, "topics": ["节日", "晚餐"],
        },
        {
            "seq": 4, "part": "late_night", "start_min": 1320, "end_min": 1430,
            "activity": "休息", "location_id": "home.bedroom",
            "variability": {"mode": "fixed"}, "user_influencable": False,
            "energy_bias": -2, "topics": ["晚安"],
        },
    ],
}


def routine_template(day_type: str) -> list[dict]:
    return ROUTINE_TEMPLATES.get(day_type, ROUTINE_TEMPLATES["weekday"])
