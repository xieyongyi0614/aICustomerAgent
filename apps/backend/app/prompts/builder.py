from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from app.character.asuna import (
    BEHAVIOR_BLOCK,
    BEHAVIOR_INSTRUCTIONS,
    IDENTITY_BLOCK,
    MODE_INSTRUCTIONS,
    PERSONALITY_BLOCK,
    RELATIONSHIP_BLOCK,
    STAGE_DESCRIPTIONS,
    STAGE_LABELS,
    describe_level,
)
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.core.settings import get_settings

MEMORY_TYPE_LABELS = {
    "user_preference": "偏好",
    "user_fact": "事实",
    "important_event": "事件",
    "relationship_event": "关系事件",
}

EMOTION_BUDGET_CHARS = 120
RELATIONSHIP_BUDGET_CHARS = 150

PERSONALITY_FIRST_CONSTRAINT = (
    "情绪叠加在你的人格之上：无论此刻情绪如何，你说话的方式、价值观和性格底色不变。"
    "温柔的角色生气时是“温柔地生气”，不是变成另一个人。"
)

EXPRESS_EMOTION_RULE = (
    "表达要求：情绪通过语气、用词和节奏自然流露，不要直接报出情绪名称或数值。"
)

TENSION_FREEZE_RULE = "最近气氛有些紧张，对话中保持一点距离感，直到氛围缓和。"


def _literal(text: str) -> str:
    """转义花括号，使动态内容不被 ChatPromptTemplate 当作模板变量。"""
    return text.replace("{", "{{").replace("}", "}}")


class PromptBuilder:
    @staticmethod
    def build_identity_sections() -> list[str]:
        return [
            IDENTITY_BLOCK,
            PERSONALITY_BLOCK,
            RELATIONSHIP_BLOCK,
            BEHAVIOR_BLOCK,
        ]

    @staticmethod
    def build_emotion_section(state: ConversationState) -> str:
        character = state.character_state
        intensity = character.intensity
        if intensity <= 0.3:
            tier = "淡淡的"
        elif intensity <= 0.6:
            tier = "明显的"
        else:
            tier = "非常强烈的"
        header = "【角色当前情绪】"
        mood_line = f"心情：{character.mood}（强度 {intensity:.1f}，{tier}）"
        budget = EMOTION_BUDGET_CHARS - len(header) - len(mood_line) - 1
        cause_line = None
        if character.cause:
            cause_text = character.cause
            if len(cause_text) + 3 > budget:
                cause_text = cause_text[: max(budget - 4, 0)] + "…"
            cause_line = f"原因：{cause_text}"
        lines = [header, mood_line]
        if cause_line:
            lines.append(cause_line)
        lines.append(EXPRESS_EMOTION_RULE)
        lines.append(PERSONALITY_FIRST_CONSTRAINT)
        return "\n".join(lines)

    @staticmethod
    def build_character_state_section(state: ConversationState) -> str:
        character = state.character_state
        energy = character.energy
        energy_level = (
            "充沛" if energy >= 0.7 else "一般" if energy >= 0.4 else "有些疲惫"
        )
        topic = character.current_topic or "还没有明确话题"
        return (
            f"【角色当前状态】\n心情：{character.mood}\n精力：{energy_level}\n"
            f"最近在聊：{topic}\n内心：{character.inner_state}"
        )

    @staticmethod
    def build_relationship_section(state: ConversationState) -> str:
        relationship = state.relationship_state
        label = STAGE_LABELS.get(relationship.stage, STAGE_LABELS["friend"])
        description = STAGE_DESCRIPTIONS.get(
            relationship.stage, STAGE_DESCRIPTIONS["friend"]
        )
        tension = relationship.tension
        if tension <= 0.3:
            tension_tier = "相处自然"
        elif tension <= 0.5:
            tension_tier = "略有尴尬"
        else:
            tension_tier = "气氛紧张"
        section = (
            f"【与用户的关系】\n当前关系：{label}（{description}）\n"
            f"亲密：{describe_level(relationship.intimacy)}　"
            f"信任：{describe_level(relationship.trust)}　"
            f"熟悉：{describe_level(relationship.familiarity)}\n"
            f"紧张度：{tension_tier}（{tension:.1f}）"
        )
        if tension > 0.5:
            section += f"\n{TENSION_FREEZE_RULE}"
        return section

    @staticmethod
    def build_behavior_section(analysis: TurnAnalysis) -> str:
        behavior = analysis.behavior.behavior
        instruction = BEHAVIOR_INSTRUCTIONS.get(
            behavior, BEHAVIOR_INSTRUCTIONS["normal_reply"]
        )
        return f"【本轮行为指令】\n{instruction}"

    @staticmethod
    def _fit_variable_parts(
        state: ConversationState, fixed_chars: int
    ) -> tuple[list, list, str | None]:
        settings = get_settings()
        budget = settings.context_total_char_budget - fixed_chars

        history = list(state.messages)
        memories = list(state.memories)
        summary = state.summary

        history_chars = sum(len(m.content) for m in history)
        memory_chars = sum(len(m.content) for m in memories)
        while history and history_chars + memory_chars > budget:
            history_chars -= len(history[0].content)
            history.pop(0)
        while memories and history_chars + memory_chars > budget:
            memory_chars -= len(memories[-1].content)
            memories.pop()
        if summary is not None:
            remaining = budget - history_chars - memory_chars
            if len(summary) > remaining:
                summary = summary[: max(remaining - 1, 0)] + "…"
        return history, memories, summary

    @staticmethod
    def build(
        mode: str,
        state: ConversationState,
        analysis: TurnAnalysis | None = None,
        scene_ctx=None,
        goal_ctx=None,
        behavior_ctx=None,
    ) -> ChatPromptTemplate:
        identity = [("system", section) for section in PromptBuilder.build_identity_sections()]
        state_sections: list[str] = []
        if analysis is not None:
            state_sections = [
                _literal(PromptBuilder.build_emotion_section(state)),
                _literal(PromptBuilder.build_character_state_section(state)),
                _literal(PromptBuilder.build_relationship_section(state)),
            ]
        tail_sections: list[str] = [
            MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["default"])
        ]
        behavior_section = None
        activity_section = None
        if analysis is not None and behavior_ctx is not None:
            from app.prompts.behavior import build_activity_section, build_behavior_section

            activity_section = build_activity_section(behavior_ctx)
            if behavior_ctx.fallback_v2 is not None:
                tail_sections.append(_literal(build_behavior_section(behavior_ctx)))
            else:
                behavior_section = build_behavior_section(behavior_ctx)
                if behavior_section is not None:
                    behavior_section = _literal(behavior_section)
            if activity_section is not None:
                activity_section = _literal(activity_section)
        elif analysis is not None:
            tail_sections.append(PromptBuilder.build_behavior_section(analysis))
        scene_budget = (
            behavior_ctx.budget
            if behavior_ctx is not None and behavior_ctx.fallback_v2 is None
            else None
        )
        if scene_ctx is not None:
            from app.prompts.scene import build_scene_sections

            tail_sections.extend(
                _literal(section) for section in build_scene_sections(scene_ctx, scene_budget)
            )
        if activity_section is not None:
            tail_sections.append(activity_section)

        from app.prompts.goal import build_goal_section, build_intention_section

        goal_section = None
        intention_section = None
        if analysis is not None and goal_ctx is not None:
            goal_section = build_goal_section(goal_ctx.selected_goal)
            intention_section = build_intention_section(goal_ctx.intention)
            if goal_section is not None:
                goal_section = _literal(goal_section)
            if intention_section is not None:
                intention_section = _literal(intention_section)

        fixed_chars = (
            sum(len(text) for _, text in identity)
            + sum(len(text) for text in state_sections)
            + sum(len(text) for text in tail_sections)
            + (len(goal_section) if goal_section else 0)
            + (len(intention_section) if intention_section else 0)
            + (len(behavior_section) if behavior_section else 0)
            + len(state.current_input)
            + 120
        )
        history, memories, summary = PromptBuilder._fit_variable_parts(state, fixed_chars)

        messages = list(identity)
        messages.extend(("system", text) for text in state_sections)
        if goal_section is not None:
            messages.append(("system", goal_section))
        if intention_section is not None:
            messages.append(("system", intention_section))
        if behavior_section is not None:
            messages.append(("system", behavior_section))

        if memories:
            memory_lines = "\n".join(
                f"- ({MEMORY_TYPE_LABELS.get(m.type, m.type)}) {m.content}"
                for m in memories
            )
            messages.append(
                (
                    "system",
                    "【你记得关于用户的事】\n"
                    f"{_literal(memory_lines)}\n"
                    "（仅在自然相关时引用，不要主动罗列；已提到过的事不要复述，除非用户问起）",
                )
            )

        if summary:
            messages.append(("system", _literal(f"【对话摘要】\n{summary}")))

        for message in history:
            if message.role == "human":
                messages.append(HumanMessage(content=message.content))
            else:
                messages.append(AIMessage(content=message.content))

        messages.extend(("system", text) for text in tail_sections)
        messages.append(HumanMessage(content=state.current_input))

        return ChatPromptTemplate.from_messages(messages)
