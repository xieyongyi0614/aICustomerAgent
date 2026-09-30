"""Memory 2.0 类型体系（design.md §3，7 类封顶）。

规范类型为 7 类；v1 遗留类型（important_event/relationship_event）在存储层保持
合法以兼容既有行，但在 v2 转正入口统一归一化：relationship_event → relationship_fact
（统一真相源裁决）、important_event → experience。DB check 约束为「7 规范 + 2 遗留」
共 9 值；v1 的 Pydantic MemoryType Literal 放宽为同集合，既有 4 值行为不变。
"""

V2_MEMORY_TYPES = (
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

STORAGE_MEMORY_TYPES = V2_MEMORY_TYPES + LEGACY_MEMORY_TYPES

DEFAULT_MEMORY_TYPE = "user_fact"

TYPE_AFFINITY_KEYWORDS = {
    "user_preference": ("喜欢", "讨厌", "偏好", "爱", "不爱", "不喜欢"),
    "user_fact": ("在哪", "工作", "住", "养", "做什么", "是谁"),
    "experience": ("面试", "经历", "发生过", "事件", "考试"),
    "relationship_fact": ("我们", "一起", "送过", "看过", "去过"),
}
"""类型亲和关键词表（权威定义，全仓唯一一份，键为 v2 规范类型名）。

评估侧（`evaluator._type_affinity`）对 `proposed_type` 先经 `normalize_type` 归一，
检索侧（`retriever._detect_query_types` / `_affinity_score`）对查询与存储类型同样
归一后消费本表；遗留类型名经 `LEGACY_TYPE_ALIASES` 映入同组，评分语义不变。
"""


def normalize_type(memory_type: str | None) -> str | None:
    """归一化为 7 规范类型之一；遗留类型映射到对应规范类型，非法返回 None。"""
    if memory_type is None:
        return None
    if memory_type in V2_MEMORY_TYPES:
        return memory_type
    return LEGACY_TYPE_ALIASES.get(memory_type)


def storage_type(memory_type: str | None) -> str | None:
    """可入库类型（7 规范 + 2 遗留均可存储，用于读侧兼容判断）。"""
    if memory_type in STORAGE_MEMORY_TYPES:
        return memory_type
    return None
