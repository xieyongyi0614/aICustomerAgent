"""V7 主动消息 Prompt（goal-integration.md §3）。

结构对齐 V6 goal-context：目标段 + 意图段 + 最近对话语境 + 主动场景表达约束。
"""

PERSONA_FIRST_CONSTRAINT = (
    "你是亚丝娜。主动的关心同样叠加在你的人格之上：温柔的人主动是贴心的问候，"
    "不改变说话方式与价值观。"
)

PROACTIVE_RULES = (
    "表达要求：这是你主动发起的一句话（用户没有在等你回复），"
    "自然开启话题、允许用户不回复、不追问施压；一句话，口语化，不使用动作描写。"
)


def build_proactive_messages(
    goal_description: str,
    intention: str,
    recent_context: str,
) -> list[tuple]:
    messages: list[tuple] = [
        ("system", PERSONA_FIRST_CONSTRAINT),
        ("system", f"【角色当前目标】主导：{goal_description}（无用户输入场景）"),
        ("system", f"【本轮意图】{intention}（主动关心用户近况）"),
    ]
    if recent_context:
        messages.append(("system", f"【最近对话】\n{recent_context}"))
    messages.append(("system", PROACTIVE_RULES))
    messages.append(("user", "请直接输出这一句话本身，不要任何解释或引号。"))
    return messages
