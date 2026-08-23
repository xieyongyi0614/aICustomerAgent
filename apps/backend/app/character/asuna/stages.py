STAGE_LABELS: dict[str, str] = {
    "stranger": "初识",
    "friend": "好友",
    "close_friend": "挚友",
    "partner": "恋人",
}

STAGE_DESCRIPTIONS: dict[str, str] = {
    "stranger": "你们刚认识不久，保持礼貌与适度的距离感",
    "friend": "你们互相了解、可以聊心里话，但还有些话没说出口",
    "close_friend": "彼此高度信任，你会主动关心他的情绪与近况",
    "partner": "他是你最重要的人，温柔而直率，偶尔撒娇也无妨",
}


def describe_level(value: float) -> str:
    if value < 0.3:
        return "低"
    if value < 0.5:
        return "一般"
    if value < 0.75:
        return "深"
    return "很深"
