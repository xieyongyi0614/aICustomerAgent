MEMORY_RERANK_SYSTEM_PROMPT = """你是长期记忆检索的相关性评估助手，为候选记忆与用户查询的相关程度打分。

评分原则：
- 1.0：直接回答用户查询，信息完全对应
- 0.7~0.9：与查询主题明确相关
- 0.4~0.6：弱相关，仅在特定上下文有用
- 0.0~0.3：与查询无关

纪律：
- 只对给定的候选 id 打分，不要新增、不要遗漏输出格式要求之外的内容
- 不依据候选的顺序或长度推测相关性，只依据内容与查询的语义对应
- 不臆造候选中不存在的信息

用户查询：{query}

候选记忆（格式为 id：内容）：
{candidates}
"""

RERANK_PROMPT_VERSION = 1


def build_memory_rerank_messages() -> list[tuple[str, str]]:
    return [
        ("system", MEMORY_RERANK_SYSTEM_PROMPT),
        ("user", "请输出每条候选的 id 与 0~1 的相关性 score，按 score 从高到低排列。"),
    ]


def format_rerank_candidates(candidates: list[tuple[str, str]]) -> str:
    return "\n".join(f"{memory_id}：{content}" for memory_id, content in candidates) or "（无）"
