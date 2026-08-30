"""V7.5 评估词表（语言级常量，非人设资产；人设矛盾模式在 character/<persona>/evaluation.py）。

动作类别归一 / 表达强度词表供规则层消费；分类失败的写法计入"其他"，不参与单调统计。
"""

import re

ACTION_DESC_RE = re.compile(r"\*[^*\n]+\*")

ACTION_CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "contact": (
        "摸头",
        "摸了摸",
        "握手",
        "牵手",
        "牵起",
        "拥抱",
        "抱住",
        "搂",
        "亲吻",
        "吻",
        "拍",
        "搭在肩",
        "拉住",
        "挽住",
        "递给",
        "递上",
        "递到",
        "蹭",
        "揉",
        "扶",
    ),
    "expression": (
        "笑",
        "脸红",
        "皱眉",
        "挑眉",
        "眨眼",
        "撇嘴",
        "瞪",
        "咧嘴",
        "扬起嘴角",
        "红了脸",
    ),
    "posture": (
        "叹气",
        "深呼吸",
        "歪头",
        "点头",
        "摇头",
        "耸肩",
        "挠头",
        "坐直",
        "靠近",
        "凑近",
        "退后",
        "起身",
        "站起",
    ),
    "movement": ("走向", "走近", "转身", "跑向", "冲向", "快步"),
}

EXPRESSION_INTENSITY_WORDS: tuple[str, ...] = (
    "开心",
    "高兴",
    "快乐",
    "难过",
    "伤心",
    "生气",
    "愤怒",
    "害怕",
    "担心",
    "激动",
    "兴奋",
    "太好了",
    "讨厌",
    "喜欢",
    "爱",
    "呜",
    "哇",
    "哈哈",
    "唉",
)


def classify_actions(text: str) -> list[str]:
    """按出现顺序返回动作类别（contact/expression/posture/movement），未归类动作忽略。"""
    categories: list[str] = []
    for match in ACTION_DESC_RE.findall(text or ""):
        category = categorize_action(match)
        if category is not None:
            categories.append(category)
    return categories


def categorize_action(action: str) -> str | None:
    for category, words in ACTION_CATEGORY_WORDS.items():
        if any(word in action for word in words):
            return category
    return None


def expression_density(text: str) -> float:
    """情绪表达密度：强度词出现次数 / 回复长度（下限 1 防除零）。"""
    if not text:
        return 0.0
    hits = sum(text.count(word) for word in EXPRESSION_INTENSITY_WORDS)
    return hits / max(len(text), 1)
