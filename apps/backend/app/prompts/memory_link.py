"""MEV-010 记忆关系抽取 prompt：判定 anchor 与候选记忆之间的三义关系。

关系白名单（★ 冻结）：`caused_by` / `before` / `related`。既有
`supersedes` / `merges` / `contradicts` 由冲突消解独占，prompt 明确禁止输出。

方向语义（与链契约一致）：
- `caused_by`：anchor **由** related 引起（anchor 是结果，related 是原因）；
- `before`：anchor 在 related **之前**发生；
- `related`：相关但无明确方向。
"""

from app.core.constants import MEMORY_LINK_EXTRACTABLE_RELATIONS

MEMORY_LINK_PROMPT_VERSION = 1

LINK_EXTRACTABLE_RELATIONS: tuple[str, ...] = MEMORY_LINK_EXTRACTABLE_RELATIONS
"""关系抽取白名单（再导出 core 常量，供链与调用方消费）。"""

RELATIONS_TEXT = "、".join(LINK_EXTRACTABLE_RELATIONS)

MEMORY_LINK_SYSTEM_PROMPT = f"""你是记忆系统的关系判定助手：判断「新记忆」与给定候选记忆之间是否存在可写入记忆图谱的关系。

关系只能取以下白名单之一：{RELATIONS_TEXT}。
- caused_by：新记忆由候选记忆引起或导致（新记忆是结果，候选是原因）。
- before：新记忆发生在候选记忆之前。
- related：相关，但没有明确的因果或时序方向。

判定纪律（逐条硬约束，违反即视为无效输出）：
1. 只能在给定候选内选择 related_memory_id，不得输出候选之外 id。
2. 没有关系就返回空 links，不要硬凑关系。
3. 不得输出 supersedes / merges / contradicts（它们由冲突消解链路独占）。
4. 每条 link 必须给出 confidence（0~1）与简短 reason。

新记忆：
{{anchor}}

候选记忆：
{{candidates}}
"""


def build_memory_link_messages() -> list[tuple[str, str]]:
    return [
        ("system", MEMORY_LINK_SYSTEM_PROMPT),
        (
            "user",
            "请输出结构化结果：links（可为空列表），每项包含 related_memory_id、"
            "relation（白名单内）、confidence（0~1）、reason（简短理由，可空）。",
        ),
    ]


def format_candidates(candidates: list[tuple[str, str]]) -> str:
    """按给定顺序列出候选 id + 内容（id 必须进入 prompt，模型需原样返回）。"""
    return (
        "\n".join(
            f"- id={memory_id} | {content}"
            for memory_id, content in candidates
        )
        or "（无）"
    )
