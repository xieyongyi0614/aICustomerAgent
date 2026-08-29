"""V6 Goal/Intention 的 Prompt 注入段（goal-context.md）。

动机先于素材：两段插在关系段之后、记忆段之前；
不暴露 goal_id/priority/status/horizon/confidence 等内部字段。
"""

from dataclasses import dataclass

from app.services.goal_service import SelectedGoal
from app.services.intention_policy import ValidatedIntention

GOAL_BUDGET_CHARS = 120
INTENTION_BUDGET_CHARS = 80

GOAL_HEADER = "【角色当前目标】"
INTENTION_HEADER = "【本轮意图】"

INTENT_EXPRESSION_RULE = (
    "表达要求：意图通过你的言行举止自然体现，不要直接说出意图名称或策略。"
)

PERSONALITY_INTENT_CONSTRAINT = (
    "意图叠加在你的人格之上：温柔的人安慰是贴近的陪伴，傲娇的人安慰是别扭的关心。"
    "用你自己的方式去达成意图，而不是套用模板。"
)

INTENTION_LABELS = {
    "comfort_user": "安抚用户",
    "suggest_rest": "建议休息",
    "encourage_user": "鼓励用户",
    "celebrate_with_user": "一起庆祝",
    "express_affection": "表达亲近",
    "tease_user": "轻微调侃",
    "maintain_distance": "保持距离",
    "repair_rapport": "修复隔阂",
    "continue_topic": "延续话题",
    "ask_followup": "追问近况",
    "share_own_feeling": "分享感受",
    "lighten_mood": "化解气氛",
}

INTENTION_DESCRIPTIONS = {
    "comfort_user": "安抚用户的情绪",
    "suggest_rest": "温柔地建议收尾或休息，不是赶人",
    "encourage_user": "给用户打气鼓劲",
    "celebrate_with_user": "和用户一起庆祝好消息",
    "express_affection": "流露对用户的亲近感",
    "tease_user": "带着亲近感轻轻调侃用户",
    "maintain_distance": "保持礼貌而克制的距离感",
    "repair_rapport": "主动缓和气氛、修复关系",
    "continue_topic": "自然延续当前话题",
    "ask_followup": "追问用户近况或细节",
    "share_own_feeling": "分享角色自己的状态或感受",
    "lighten_mood": "用轻松的方式化解尴尬或低落",
}


@dataclass
class GoalContext:
    selected_goal: SelectedGoal | None
    intention: ValidatedIntention | None


def build_goal_section(selected_goal: SelectedGoal | None) -> str | None:
    if selected_goal is None or selected_goal.goal is None:
        return None
    goal = selected_goal.goal
    lead = f"主导：{goal.description}"
    remaining = GOAL_BUDGET_CHARS - len(lead) - 1

    lines = [GOAL_HEADER, lead]
    reason = selected_goal.reason
    if reason:
        if len(reason) + 3 > remaining:
            reason = reason[: max(remaining - 4, 0)] + "…"
        lines.append(f"因为：{reason}")
        remaining -= len(reason) + 3

    background = selected_goal.suppressed_description
    if background and remaining > 12:
        text = f"暂时放下“{background}”，先{goal.description}"
        if len(text) + 5 <= remaining:
            lines.append(f"内心倾向：{text}")
    return "\n".join(lines)


def build_intention_section(intention: ValidatedIntention | None) -> str | None:
    if intention is None:
        return None
    label = INTENTION_LABELS.get(intention.intention, intention.intention)
    description = INTENTION_DESCRIPTIONS.get(intention.intention, "")
    intent_line = f"{label}（{description}）"
    if len(intent_line) > INTENTION_BUDGET_CHARS:
        intent_line = intent_line[:INTENTION_BUDGET_CHARS]
    return "\n".join(
        [
            INTENTION_HEADER,
            intent_line,
            INTENT_EXPRESSION_RULE,
            PERSONALITY_INTENT_CONSTRAINT,
        ]
    )
