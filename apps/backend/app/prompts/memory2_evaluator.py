MEMORY_EVALUATOR_SYSTEM_PROMPT = """你是记忆系统的评估助手，判断一条候选记忆是否值得长期保存。

判定原则：
- 与既有同主题记忆重复、没有新信息 → 不保存
- 瞬时请求、寒暄、一次性行动安排 → 不保存
- 疑似错误信息、无依据的推测 → 不保存
- 用户偏好、身份事实、共同经历、双方约定、重要事件 → 保存

只依据给出的候选内容与既有同主题记忆判断，不要臆造信息。"""


def build_memory_evaluation_messages(
    content: str, proposed_type: str, related_contents: list[str]
) -> list[tuple[str, str]]:
    related = "\n".join(f"- {item}" for item in related_contents) or "（无）"
    user_prompt = (
        f"候选内容：{content}\n"
        f"候选类型：{proposed_type}\n"
        f"既有同主题记忆：\n{related}\n\n"
        "请输出结构化结果：approve（布尔，是否保存）、type（记忆类型建议，可空）、"
        "reason（简短理由）。"
    )
    return [
        ("system", MEMORY_EVALUATOR_SYSTEM_PROMPT),
        ("user", user_prompt),
    ]
