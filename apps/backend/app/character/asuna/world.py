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
}

LOCATION_ALIASES = {
    "家": "home",
    "客厅": "home.living_room",
    "厨房": "home.kitchen",
    "卧室": "home.bedroom",
    "房间": "home.bedroom",
    "阳台": "home.balcony",
    "冰箱": "home.kitchen.fridge",
}

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
            "eat": {"from": ["cut"], "to": "eaten"},
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
