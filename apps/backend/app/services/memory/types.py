"""Memory 2.0 类型体系（design.md §3，7 类封顶）。

**存储词表 = 7 个规范类型**（`memories.type` CHECK 与 `UserMemory.type` 同域）。
历史遗留类型（`important_event` / `relationship_event`）已**退役**（2026-10-16，迁移 `0010`）：
存储层不再接受这两值；它们只在**入站归一**处保留（LLM 输出、旧客户端参数、旧库行），
经 `normalize_type` 映入对应规范类型后方可落库。
"""

import logging

from app.core.constants import DEFAULT_LAYER, LAYER_FOR_TYPE, MEMORY_LAYERS

logger = logging.getLogger(__name__)

__all__ = [
    "CANONICAL_MEMORY_TYPES",
    "DEFAULT_LAYER",
    "DEFAULT_MEMORY_TYPE",
    "LAYER_FOR_TYPE",
    "LEGACY_MEMORY_TYPES",
    "LEGACY_TYPE_ALIASES",
    "MEMORY_LAYERS",
    "TYPE_AFFINITY_KEYWORDS",
    "layer_for_type",
    "normalize_type",
]
"""公开面：词表 / 层词汇（再导出自身份真源）/ 两个纯函数。"""

CANONICAL_MEMORY_TYPES = (
    "user_preference",
    "user_fact",
    "experience",
    "relationship_fact",
    "commitment",
    "milestone_event",
    "behavior_pattern",
)

DEFAULT_MEMORY_TYPE = "user_fact"

LEGACY_TYPE_ALIASES = {
    "important_event": "experience",
    "relationship_event": "relationship_fact",
}
"""入站归一表（历史类型名 → 规范类型名）：仅入口 / 读侧归一使用，**不属存储词表**。"""

LEGACY_MEMORY_TYPES = tuple(LEGACY_TYPE_ALIASES)
"""入站兼容名（= 归一表键集）：存储层不接受这些值，落库前一律归一。"""

# 层词汇（`MEMORY_LAYERS` / `DEFAULT_LAYER` / `LAYER_FOR_TYPE`）定义在 `app/core/constants.py`
# 并在本模块**再导出**（单一真源）：低层定义便于仓储写入路径直接消费，本模块另提供带类型归一的
# `layer_for_type()`（见文件末）。

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


def layer_for_type(memory_type: str | None) -> str:
    """类型 → 通道层（纯函数）：先经 `normalize_type` 归一（遗留名同样可判层）。

    未命中 → `logger.warning` + `DEFAULT_LAYER`（**不抛**，对齐记忆域降级纪律）。
    """
    canonical = normalize_type(memory_type) or memory_type
    layer = LAYER_FOR_TYPE.get(canonical or "")
    if layer is None:
        logger.warning("unknown memory type for layer: %s", memory_type)
        return DEFAULT_LAYER
    return layer
