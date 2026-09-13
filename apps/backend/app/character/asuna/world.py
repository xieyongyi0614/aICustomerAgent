"""亚丝娜世界设定资产（V8-001，world-model.md §2 / location-system.md §1）。

世界"设定"（静态）：地点布局、物品状态机、环境词表——与世界"状态"（worlds 表）分离。
"""

HOME_LOCATIONS = {
    "home": {
        "name": "家",
        "parent_id": None,
        "traits": ["indoor"],
        "available_actions": ["休息", "聊天"],
        "description": "你和亚丝娜的家",
    },
    "home.living_room": {
        "name": "客厅",
        "parent_id": "home",
        "traits": ["indoor", "quiet"],
        "available_actions": ["休息", "聊天", "看电视"],
    },
    "home.kitchen": {
        "name": "厨房",
        "parent_id": "home",
        "traits": ["indoor", "food_related"],
        "available_actions": ["拿食物", "做饭", "收拾"],
    },
    "home.bedroom": {
        "name": "卧室",
        "parent_id": "home",
        "traits": ["indoor", "quiet"],
        "available_actions": ["休息", "睡觉"],
    },
    "home.balcony": {
        "name": "阳台",
        "parent_id": "home",
        "traits": ["indoor", "outdoor_exposed"],
        "available_actions": ["晾衣服", "透气"],
    },
    "home.kitchen.fridge": {
        "name": "冰箱",
        "parent_id": "home.kitchen",
        "traits": ["indoor", "container", "food_related"],
        "available_actions": ["打开", "拿食物"],
    },
    "home.kitchen.cabinet": {
        "name": "橱柜",
        "parent_id": "home.kitchen",
        "traits": ["indoor", "container", "food_related"],
        "available_actions": ["打开", "拿食物"],
    },
    "home.bathroom": {
        "name": "浴室",
        "parent_id": "home",
        "traits": ["indoor"],
        "available_actions": ["洗漱", "洗澡"],
    },
    "home.dining_area": {
        "name": "餐桌",
        "parent_id": "home.living_room",
        "traits": ["indoor", "food_related"],
        "available_actions": ["用餐", "摆放"],
    },
}

LOCATION_ALIASES = {
    "家": "home",
    "客厅": "home.living_room",
    "厨房": "home.kitchen",
    "卧室": "home.bedroom",
    "房间": "home.bedroom",
    "阳台": "home.balcony",
    "浴室": "home.bathroom",
    "卫生间": "home.bathroom",
    "冰箱": "home.kitchen.fridge",
    "橱柜": "home.kitchen.cabinet",
    "餐桌": "home.dining_area",
    "饭桌": "home.dining_area",
    "桌面": "home.dining_area",
    "桌上": "home.dining_area",
}

WORLD_LOCATIONS = {
    "school": {
        "name": "学校",
        "parent_id": None,
        "traits": ["indoor", "outdoor_exposed"],
        "available_actions": ["上课", "学习", "聊天"],
        "description": "亚丝娜就读的学校",
    },
    "school.classroom": {
        "name": "教室",
        "parent_id": "school",
        "traits": ["indoor", "quiet"],
        "available_actions": ["上课", "学习", "聊天"],
    },
    "school.library": {
        "name": "图书馆",
        "parent_id": "school",
        "traits": ["indoor", "quiet"],
        "available_actions": ["学习", "看书"],
    },
    "school.playground": {
        "name": "操场",
        "parent_id": "school",
        "traits": ["outdoor_exposed"],
        "available_actions": ["运动", "散步"],
    },
    "company": {
        "name": "公司",
        "parent_id": None,
        "traits": ["indoor"],
        "available_actions": ["工作", "开会"],
        "description": "工作的地方",
    },
    "company.workstation": {
        "name": "工位",
        "parent_id": "company",
        "traits": ["indoor", "quiet"],
        "available_actions": ["工作"],
    },
    "company.meeting_room": {
        "name": "会议室",
        "parent_id": "company",
        "traits": ["indoor"],
        "available_actions": ["开会", "讨论"],
    },
    "cafe": {
        "name": "咖啡店",
        "parent_id": None,
        "traits": ["indoor", "food_related", "public"],
        "available_actions": ["点单", "聊天", "休息"],
        "description": "常去的咖啡店",
    },
    "cafe.main": {
        "name": "咖啡店堂区",
        "parent_id": "cafe",
        "traits": ["indoor", "food_related", "public"],
        "available_actions": ["点单", "聊天", "休息"],
    },
    "cafe.terrace": {
        "name": "咖啡店露台",
        "parent_id": "cafe",
        "traits": ["outdoor_exposed", "food_related", "public"],
        "available_actions": ["点单", "聊天", "透气"],
    },
    "park": {
        "name": "公园",
        "parent_id": None,
        "traits": ["outdoor_exposed"],
        "available_actions": ["散步", "休息"],
        "description": "附近的公园",
    },
    "park.path": {
        "name": "公园步道",
        "parent_id": "park",
        "traits": ["outdoor_exposed"],
        "available_actions": ["散步", "跑步"],
    },
    "park.bench": {
        "name": "公园长椅",
        "parent_id": "park",
        "traits": ["outdoor_exposed", "quiet"],
        "available_actions": ["休息", "聊天"],
    },
    "travel_seaside": {
        "name": "海边",
        "parent_id": None,
        "traits": ["outdoor_exposed", "travel"],
        "available_actions": ["散步", "看海", "休息"],
        "description": "旅行目的地：海边",
    },
    "travel_hotel": {
        "name": "旅行酒店",
        "parent_id": None,
        "traits": ["indoor", "travel"],
        "available_actions": ["休息", "睡觉"],
        "description": "旅行住宿的酒店",
    },
}

WORLD_LOCATION_REGISTRY = {**HOME_LOCATIONS, **WORLD_LOCATIONS}

LOCATION_ALIASES.update(
    {
        "学校": "school",
        "教室": "school.classroom",
        "图书馆": "school.library",
        "操场": "school.playground",
        "公司": "company",
        "工位": "company.workstation",
        "会议室": "company.meeting_room",
        "咖啡店": "cafe.main",
        "咖啡馆": "cafe.main",
        "咖啡厅": "cafe.main",
        "咖啡店露台": "cafe.terrace",
        "公园": "park.path",
        "长椅": "park.bench",
        "公园长椅": "park.bench",
        "步道": "park.path",
        "海边": "travel_seaside",
        "海滩": "travel_seaside",
        "沙滩": "travel_seaside",
        "旅行酒店": "travel_hotel",
        "酒店": "travel_hotel",
    }
)

WORLD_WEATHER_VALUES = ("sunny", "cloudy", "rain", "snow", "windy")

WEATHER_ALIASES = {
    "下雨": "rain",
    "下雪": "snow",
    "晴天": "sunny",
    "天晴": "sunny",
    "出太阳": "sunny",
    "阴天": "cloudy",
    "刮风": "windy",
}

ENVIRONMENT_EFFECT_NOTES = {
    "rain": "雨天不适合出门",
    "snow": "雪天路滑注意保暖",
    "windy": "风大记得关好门窗",
}

OBJECT_STATE_MACHINES = {
    "food": {
        "initial": "whole",
        "default_portions": 5,
        "transitions": {
            "cut": {"from": ["whole"], "to": "cut"},
            "eat": {"from": ["cut", "eaten"], "to": "eaten"},
            "expire": {"from": ["whole", "cut"], "to": "expired"},
            "discard": {"from": ["whole", "cut"], "to": "empty"},
        },
    },
    "drink": {
        "initial": "sealed",
        "default_portions": 3,
        "transitions": {
            "open": {"from": ["sealed"], "to": "opened"},
            "eat": {"from": ["opened"], "to": "opened"},
            "expire": {"from": ["sealed", "opened"], "to": "expired"},
            "discard": {"from": ["sealed", "opened"], "to": "empty"},
        },
    },
    "device": {
        "initial": "off",
        "default_portions": 1,
        "transitions": {
            "open": {"from": ["off"], "to": "on"},
            "close": {"from": ["on"], "to": "off"},
            "discard": {"from": ["*"], "to": "empty"},
        },
    },
    "generic": {
        "initial": "intact",
        "default_portions": 1,
        "transitions": {
            "open": {"from": ["intact", "closed"], "to": "open"},
            "close": {"from": ["open"], "to": "closed"},
            "damage": {"from": ["*"], "to": "damaged"},
            "discard": {"from": ["*"], "to": "destroyed"},
        },
    },
}

EVENT_TYPE_ALIASES = {
    "面试": "interview",
    "考试": "exam",
    "约会": "appointment",
    "旅行": "trip",
    "生日": "birthday",
    "会议": "meeting",
    "体检": "appointment",
}

EVENT_IMPORTANCE_DEFAULT = {
    "interview": "high",
    "exam": "high",
    "trip": "normal",
    "appointment": "normal",
    "birthday": "high",
    "meeting": "normal",
}

EVENT_TYPE_TITLES = {
    "interview": "面试",
    "exam": "考试",
    "appointment": "预约",
    "trip": "旅行",
    "birthday": "生日",
    "meeting": "会议",
}

OBJECT_CREATION_HINTS = {
    "西瓜": "food",
    "蛋糕": "food",
    "披萨": "food",
    "面包": "food",
    "可乐": "drink",
    "果汁": "drink",
    "咖啡豆": "drink",
}

DEFAULT_HOUSEHOLD = {
    "name": "默认家庭库存",
    "objects": [
        {
            "name": "鸡蛋",
            "category": "food",
            "location_id": "home.kitchen.fridge",
            "quantity": 6,
            "unit": "piece",
            "consumable": True,
        },
        {
            "name": "牛奶",
            "category": "drink",
            "location_id": "home.kitchen.fridge",
            "quantity": 1,
            "unit": "piece",
            "consumable": True,
        },
        {
            "name": "可乐",
            "category": "drink",
            "location_id": "home.kitchen.fridge",
            "quantity": 2,
            "unit": "piece",
            "consumable": True,
        },
        {
            "name": "面条",
            "category": "food",
            "location_id": "home.kitchen.cabinet",
            "quantity": 2,
            "unit": "piece",
            "consumable": True,
        },
        {
            "name": "大米",
            "category": "food",
            "location_id": "home.kitchen.cabinet",
            "quantity": 2,
            "unit": "kg",
            "consumable": True,
        },
        {
            "name": "面包",
            "category": "food",
            "location_id": "home.kitchen.cabinet",
            "quantity": 1,
            "unit": "piece",
            "consumable": True,
        },
    ],
}
