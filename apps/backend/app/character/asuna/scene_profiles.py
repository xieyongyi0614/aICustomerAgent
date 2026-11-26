"""亚丝娜场景画像资产（V2.3.0 WS-006，architecture.md §5.5）。

每地点的 atmosphere / tone / 话题可供性 / 表达上限 / 能量基线；
未注册地点回落 DEFAULT_SCENE_PROFILE（中性档）。
"""

from app.models.world_simulation import SceneProfile

SCENE_PROFILES: dict[str, dict] = {
    "home": {
        "atmosphere_tags": ["放松", "私密"],
        "tone_bias": "intimate",
        "topic_affordances": ["日常", "家常话题"],
        "expressiveness_cap": "rich",
        "energy_bias": 0,
    },
    "school": {
        "atmosphere_tags": ["充实", "规律"],
        "tone_bias": "focused",
        "topic_affordances": ["学习", "校园"],
        "expressiveness_cap": "natural",
        "energy_bias": 1,
    },
    "company": {
        "atmosphere_tags": ["忙碌", "专注"],
        "tone_bias": "focused",
        "topic_affordances": ["工作", "效率"],
        "expressiveness_cap": "subtle",
        "energy_bias": 0,
    },
    "cafe": {
        "atmosphere_tags": ["惬意", "香气"],
        "tone_bias": "casual",
        "topic_affordances": ["闲聊", "分享", "日常"],
        "expressiveness_cap": "rich",
        "energy_bias": 1,
        "mood_bias": "relaxed",
    },
    "park": {
        "atmosphere_tags": ["开阔", "自然"],
        "tone_bias": "casual",
        "topic_affordances": ["闲聊", "散步见闻"],
        "expressiveness_cap": "natural",
        "energy_bias": 1,
    },
    "travel_seaside": {
        "atmosphere_tags": ["开阔", "海风"],
        "tone_bias": "casual",
        "topic_affordances": ["旅行见闻", "风景"],
        "expressiveness_cap": "rich",
        "energy_bias": 2,
        "mood_bias": "refreshed",
    },
    "travel_hotel": {
        "atmosphere_tags": ["旅途", "安静"],
        "tone_bias": "intimate",
        "topic_affordances": ["旅途计划", "休整"],
        "expressiveness_cap": "natural",
        "energy_bias": 0,
    },
}

DEFAULT_SCENE_PROFILE = SceneProfile(location_id="default")

_EXPRESSIVENESS_ORDER = ("subtle", "natural", "rich")


def scene_profile_for(location_id: str) -> SceneProfile:
    raw = SCENE_PROFILES.get(location_id)
    if raw is None:
        root = location_id.split(".")[0]
        raw = SCENE_PROFILES.get(root)
    if raw is None:
        return DEFAULT_SCENE_PROFILE.model_copy(update={"location_id": location_id})
    return SceneProfile(location_id=location_id, **raw)


def cap_expression(level: str, cap: str) -> str:
    """表达档只降不升：情绪档超出场景上限时取 min。"""
    if level not in _EXPRESSIVENESS_ORDER or cap not in _EXPRESSIVENESS_ORDER:
        return level
    return min(level, cap, key=_EXPRESSIVENESS_ORDER.index)
