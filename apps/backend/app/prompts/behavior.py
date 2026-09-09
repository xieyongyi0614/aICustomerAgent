"""V6.5 Response Style Controller 渲染（response-controller.md §3~5）。

把 BehaviorDirective 渲染为【表现方式】/【活动延续】段。约束短句，非模板。
"""

from app.models.behavior_strategy import BehaviorDirective

BEHAVIOR_SECTION_BUDGET_CHARS = 200
ACTIVITY_SECTION_BUDGET_CHARS = 100

CONSTRAINT_ANCHOR = "以上是表达方式约束，内容仍由你根据对话自然决定。"

BUDGET_LINES = {
    0: "本轮不做动作描写；情绪通过语气流露。",
    1: "最多 1 个动作描写，放在最关键处。",
    2: "动作描写不超过 2 处，不连续堆叠。",
}

PROFESSIONAL_BUDGET_LINE = "本轮不做任何动作描写，直接用语言回应。"

CONTACT_LINES = {
    "light": "可以有轻度的身体动作（如递东西、整理衣角），不做更亲密的接触。",
    "moderate": "可以有中度的身体动作（如牵手、轻拍肩膀），不做更亲密的接触。",
}


def build_behavior_section(directive: BehaviorDirective | None) -> str | None:
    if directive is None:
        return None
    if directive.fallback_directive is not None:
        lines = ["【本轮行为指令】", directive.fallback_directive]
        budget_line = _budget_line(directive)
        if budget_line:
            lines.append(budget_line)
        return "\n".join(lines)
    if directive.strategy.degraded:
        return None
    lines = ["【表现方式】"]
    instruction = directive.strategy.instruction
    if instruction:
        lines.append(f"这一轮：{instruction}")
    mood_tone = directive.strategy.mood_tone
    if mood_tone:
        lines.append(f"语气方向：{mood_tone}")
    if directive.development_style is not None and directive.development_style.tone_hint:
        lines.append(f"风格调整：{directive.development_style.tone_hint}")
    if directive.development_care_hint:
        lines.append(f"此刻的在意：{directive.development_care_hint}")
    for habit in directive.habits[:2]:
        lines.append(f"表达习惯：{habit.instruction}")
    budget_line = _budget_line(directive)
    if budget_line:
        lines.append(budget_line)
    lines.append(CONSTRAINT_ANCHOR)
    return "\n".join(lines)


def _budget_line(directive: BehaviorDirective) -> str | None:
    budget = directive.budget
    if not budget.allow_action_desc:
        return PROFESSIONAL_BUDGET_LINE
    if budget.max_action_desc == 0:
        return BUDGET_LINES[0]
    contact = CONTACT_LINES.get(budget.physical_contact)
    if budget.max_action_desc == 2:
        line = BUDGET_LINES[2]
        return f"{line}{contact or ''}"
    if budget.max_action_desc == 1 and contact is not None:
        return f"{BUDGET_LINES[1]}{contact}"
    if budget.physical_contact != "none":
        return contact
    return None


def build_activity_section(directive: BehaviorDirective | None) -> str | None:
    if directive is None:
        return None
    if directive.activity in ("idle", "pending_obligation"):
        return None
    text = directive.activity_text
    if not text:
        return None
    return (
        "【活动延续】\n"
        f"你正在做的事：{text}。回答这轮话题时自然带着这个状态"
        "（手上动作、注意力分配），不要凭空停下或无视它；"
        "除非用户话题直接涉及当前活动。"
    )
