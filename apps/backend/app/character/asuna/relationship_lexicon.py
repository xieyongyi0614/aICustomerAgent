"""V8.5 角色资产：关系词表与档位文案（relationship_lexicon）。

001 交付两维档位文案（relationship-model.md §7）；
002 填充启发式信号词表，005 填充恢复词表，004 填充里程碑目录，006 填充记忆模板。
"""

RESPECT_LEVEL_TEXTS: dict[str, str] = {
    "low": "言行让你有些失望",
    "mid": "保持应有的尊重",
    "high": "由衷敬佩",
}

COMFORT_LEVEL_TEXTS: dict[str, str] = {
    "low": "相处有些放不开",
    "mid": "相处还算自在",
    "high": "相处毫无负担",
}

DEFAULT_RESPECT = 0.60
DEFAULT_COMFORT = 0.60


def describe_respect(value: float) -> str:
    if value < 0.4:
        return RESPECT_LEVEL_TEXTS["low"]
    if value <= 0.7:
        return RESPECT_LEVEL_TEXTS["mid"]
    return RESPECT_LEVEL_TEXTS["high"]


def describe_comfort(value: float) -> str:
    if value < 0.4:
        return COMFORT_LEVEL_TEXTS["low"]
    if value <= 0.7:
        return COMFORT_LEVEL_TEXTS["mid"]
    return COMFORT_LEVEL_TEXTS["high"]


SIGNAL_LEXICON: tuple[tuple[tuple[str, ...], str, str, float], ...] = (
    (("别过界", "不许这样说", "你越界了", "少管我", "滚"), "boundary_violation", "negative", 0.7),
    (("你怎么这样", "说话不算话", "你骗我", "食言"), "promise", "negative", 0.6),
    (("我答应你", "说到做到", "我会兑现", "我说到做到"), "promise", "positive", 0.6),
    (("说真的", "其实我一直", "别告诉别人", "我只告诉你", "心里藏着", "坦白说"), "self_disclosure", "positive", 0.6),
    (("谢谢", "多亏了你", "太感谢", "感激", "多谢"), "gratitude", "positive", 0.5),
    (("你太厉害了", "真有你的", "好厉害", "太棒了", "佩服", "了不起"), "appreciation", "positive", 0.4),
    (("别难过", "会好的", "加油", "我陪你", "支持你", "别伤心", "振作"), "support", "positive", 0.5),
    (("帮帮我", "能帮我", "求助", "怎么办", "你可以帮我吗"), "request_help", "positive", 0.5),
    (("我教你", "你应该", "我的建议是", "要不要试试", "告诉你个方法"), "teaching", "positive", 0.4),
    (("哈哈", "真好笑", "搞笑", "逗", "笑死"), "humor", "positive", 0.3),
    (("一起", "我们俩", "一起去", "陪我一起"), "shared_activity", "positive", 0.4),
    (("讨厌你", "烦你", "不想理你", "跟你没完", "吵"), "conflict", "negative", 0.7),
    (("你真差劲", "失望透顶", "埋怨", "都怪你", "抱怨"), "criticism", "negative", 0.6),
)

SENSITIVE_LEXICON = tuple(
    entry for entry in SIGNAL_LEXICON if entry[2] == "negative"
)

RECOVERY_LEXICON: tuple[str, ...] = (
    "对不起",
    "抱歉",
    "我错了",
    "是我不好",
    "别生气了",
    "原谅我",
    "我不是故意的",
)

MEMORY_TEMPLATES: dict[str, str] = {
    "first_self_disclosure": "TA 第一次向我敞开心扉，说起了{cause}。",
    "first_support_in_distress": "我最低落的时候，是 TA 陪着我。",
    "first_promise_kept": "TA 答应过我的事，做到了。",
    "first_shared_activity": "我们一起完成过一件事。",
    "first_conflict": "我们争吵过，为了{cause}。",
    "conflict": "我们争吵过，为了{cause}。",
    "reconciled": "我们和好了。经过那次争吵，我更珍惜现在的相处。",
    "promise_broken": "TA 曾答应我的事没有做到。",
    "boundary_violation": "TA 曾越过我的边界。",
}
