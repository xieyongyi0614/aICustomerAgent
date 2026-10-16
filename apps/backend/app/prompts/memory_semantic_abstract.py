"""MEV-007 语义抽象 prompt：若干情景经历 → 一条跨事件语义结论。

四条纪律（`docs/version/v6.0.0/tasks/MEV-007.md` §4.1.1「prompt 纪律」）：

1. 只做归纳，不得虚构未出现的事实；
2. 类型只能取白名单值；
3. 禁止出现金额、账号、流水等账目明细；
4. 输出长度上限。

词表与长度上限**在本模块冻结**（prompt 文本需内联它们），链侧
（`app/chains/memory_semantic_abstract_chain.py`）再导出为 `SEMANTIC_TYPES` /
`SEMANTIC_CONTENT_MAX_CHARS`，以满足链契约的符号命名。
"""

SEMANTIC_ABSTRACT_PROMPT_VERSION = 1

SEMANTIC_TYPES: tuple[str, ...] = (
    "user_preference",
    "user_fact",
    "behavior_pattern",
    "relationship_fact",
    "commitment",
)
"""语义抽象允许类型白名单（★ 冻结，顺序即展示顺序）。

**不得**包含 `experience` / `milestone_event`——它们是情景类型（`layer='episodic'`），
作为语义抽象产物会造成层与类型的语义混乱（`MEV-007` §4.1.1 / D1）。
"""

SEMANTIC_CONTENT_MAX_CHARS = 200
"""结论长度上限（字）：超出即由链 fail-closed 拒绝（不截断——截断会产生残缺结论）。"""

SEMANTIC_TYPES_TEXT = "、".join(SEMANTIC_TYPES)

SEMANTIC_ABSTRACT_SYSTEM_PROMPT = f"""你是记忆系统的语义归纳助手：把用户在同一主题下的若干段情景经历，归纳为一条关于用户的稳定认识。

归纳纪律（逐条硬约束，违反即视为无效输出）：
1. 只做归纳：结论必须能由给定的情景经历直接支持，不得虚构未出现的事实，不得补全细节。
2. 类型只能取以下白名单之一：{SEMANTIC_TYPES_TEXT}；白名单之外的类型一律不要输出。
3. 禁止出现金额、账号、卡号、流水、账单等账目明细；记忆只承接抽象模式，不承接流水。
4. 只输出 1 条结论，用一句陈述句表达，不超过 {SEMANTIC_CONTENT_MAX_CHARS} 字。

主题：{{theme}}

情景经历（按发生时间升序）：
{{episodes}}
"""


def build_semantic_abstract_messages() -> list[tuple[str, str]]:
    return [
        ("system", SEMANTIC_ABSTRACT_SYSTEM_PROMPT),
        (
            "user",
            "请输出结构化结果：items（**恰好 1 条**），其中 content（一句陈述句结论）、"
            "proposed_type（白名单内的类型）、reason（简短理由，可空）。",
        ),
    ]


def format_episodes(episodes: list[tuple[str, str]]) -> str:
    """按给定顺序编号列出情景内容（不把 memory_id 送进 prompt，减少噪声）。"""
    return (
        "\n".join(
            f"{index}. {content}"
            for index, (_, content) in enumerate(episodes, start=1)
        )
        or "（无）"
    )
