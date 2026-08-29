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

MEMORY_TYPE_LABELS = {
    "user_preference": "偏好",
    "user_fact": "事实",
    "important_event": "事件",
    "relationship_event": "关系事件",
}


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
        return (
            f"【与用户的关系】\n当前关系：{label}（{description}）\n"
            f"亲密：{describe_level(relationship.intimacy)}　"
            f"信任：{describe_level(relationship.trust)}　"
            f"熟悉：{describe_level(relationship.familiarity)}"
        )

    @staticmethod
    def build_behavior_section(analysis: TurnAnalysis) -> str:
        behavior = analysis.behavior.behavior
        instruction = BEHAVIOR_INSTRUCTIONS.get(
            behavior, BEHAVIOR_INSTRUCTIONS["normal_reply"]
        )
        return f"【本轮行为指令】\n{instruction}"

    @staticmethod
    def build(
        mode: str,
        state: ConversationState,
        analysis: TurnAnalysis | None = None,
        scene_ctx=None,
    ) -> ChatPromptTemplate:
        messages = [("system", section) for section in PromptBuilder.build_identity_sections()]

        if analysis is not None:
            messages.append(("system", PromptBuilder.build_character_state_section(state)))
            messages.append(("system", PromptBuilder.build_relationship_section(state)))

        if state.memories:
            memory_lines = "\n".join(
                f"- ({MEMORY_TYPE_LABELS.get(m.type, m.type)}) {m.content}"
                for m in state.memories
            )
            messages.append(
                (
                    "system",
                    "【你记得关于用户的事】\n"
                    f"{memory_lines}\n"
                    "（仅在自然相关时引用，不要主动罗列；已提到过的事不要复述，除非用户问起）",
                )
            )

        if state.summary:
            messages.append(("system", f"【对话摘要】\n{state.summary}"))

        for message in state.messages:
            messages.append((message.role, message.content))

        mode_instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["default"])
        messages.append(("system", mode_instruction))

        if analysis is not None:
            messages.append(("system", PromptBuilder.build_behavior_section(analysis)))

        if scene_ctx is not None:
            from app.prompts.scene import build_scene_sections

            for section in build_scene_sections(scene_ctx):
                messages.append(("system", section))

        messages.append(("human", state.current_input))

        return ChatPromptTemplate.from_messages(messages)
