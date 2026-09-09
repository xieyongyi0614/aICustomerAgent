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
