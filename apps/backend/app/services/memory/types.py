"""Memory 2.0 类型体系（design.md §3，7 类封顶）。

规范类型为 7 类；v1 遗留类型（important_event/relationship_event）在存储层保持
合法以兼容既有行，但在 v2 转正入口统一归一化：relationship_event → relationship_fact
（统一真相源裁决）、important_event → experience。DB check 约束为「7 规范 + 2 遗留」
共 9 值；v1 的 Pydantic MemoryType Literal 放宽为同集合，既有 4 值行为不变。
"""

CANONICAL_MEMORY_TYPES = (
    "user_preference",
    "user_fact",
    "experience",
    "relationship_fact",
    "commitment",
    "milestone_event",
    "behavior_pattern",
)

LEGACY_MEMORY_TYPES = ("important_event", "relationship_event")

LEGACY_TYPE_ALIASES = {
    "important_event": "experience",
    "relationship_event": "relationship_fact",
}

STORAGE_MEMORY_TYPES = CANONICAL_MEMORY_TYPES + LEGACY_MEMORY_TYPES

DEFAULT_MEMORY_TYPE = "user_fact"

TYPE_AFFINITY_KEYWORDS = {
    "user_preference": (
        "喜欢",
        "讨厌",
        "偏好",
        "爱",
        "不爱",
        "不喜欢",
        "喜爱",
        "最爱",
        "爱吃",
        "感兴趣",
        "口味",
    ),
    "user_fact": (
        "在哪",
        "工作",
        "住",
        "养",
        "做什么",
        "是谁",
        "住在",
        "老家",
        "家乡",
        "职业",
        "年龄",
        "名字",
    ),
    "experience": (
        "面试",
        "经历",
        "发生过",
        "事件",
        "考试",
        "参加",
        "遇到",
        "碰见",
        "那天",
        "出差",
        "旅行",
        "搬家",
        "比赛",
        "答辩",
    ),
    "relationship_fact": (
        "我们",
        "一起",
        "送过",
        "看过",
        "去过",
        "陪我",
        "带我",
        "约过",
        "聊过",
        "见过",
        "相处",
        "认识",
        "约会",
        "礼物",
        "合照",
    ),
    "commitment": (
        "承诺",
        "答应",
        "约定",
        "说好",
        "约好",
        "保证",
        "打算",
        "计划",
        "别忘",
    ),
    "milestone_event": (
        "里程碑",
        "纪念日",
        "第一次",
        "首次",
        "周年",
        "生日",
        "达成",
        "升级",
    ),
    "behavior_pattern": (
        "习惯",
        "经常",
        "总是",
        "每次",
        "每天",
        "一直",
        "规律",
        "老是",
        "向来",
        "通常",
    ),
}
"""类型亲和关键词表（权威定义，全仓唯一一份，键为 v2 规范类型名，覆盖全部 7 类）。

评估侧（`evaluator._type_affinity`）对 `proposed_type` 先经 `normalize_type` 归一，
检索侧（`retriever._detect_query_types` / `_affinity_score`）对查询与存储类型同样
归一后消费本表；遗留类型名经 `LEGACY_TYPE_ALIASES` 映入同组，评分语义不变。
键集合与 `CANONICAL_MEMORY_TYPES` 一一对应（有静态用例钉住），新增类型必须同步扩表。
"""


def normalize_type(memory_type: str | None) -> str | None:
    """归一化为 7 规范类型之一；遗留类型映射到对应规范类型，非法返回 None。"""
    if memory_type is None:
        return None
    if memory_type in CANONICAL_MEMORY_TYPES:
        return memory_type
    return LEGACY_TYPE_ALIASES.get(memory_type)


def storage_type(memory_type: str | None) -> str | None:
    """可入库类型（7 规范 + 2 遗留均可存储，用于读侧兼容判断）。"""
    if memory_type in STORAGE_MEMORY_TYPES:
        return memory_type
    return None
