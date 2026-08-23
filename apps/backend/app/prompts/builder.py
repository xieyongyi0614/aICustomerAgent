from langchain_core.prompts import ChatPromptTemplate

from app.character.asuna import (
    BEHAVIOR_BLOCK,
    IDENTITY_BLOCK,
    MODE_INSTRUCTIONS,
    PERSONALITY_BLOCK,
    RELATIONSHIP_BLOCK,
)
from app.models.conversation import ConversationState


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
    def build(mode: str, state: ConversationState) -> ChatPromptTemplate:
        messages = [("system", section) for section in PromptBuilder.build_identity_sections()]

        if state.memories:
            memory_lines = "\n".join(f"- {m.memory}" for m in state.memories)
            messages.append(("system", f"【用户记忆】\n{memory_lines}"))

        if state.summary:
            messages.append(("system", f"【对话摘要】\n{state.summary}"))

        for message in state.messages:
            messages.append((message.role, message.content))

        mode_instruction = MODE_INSTRUCTIONS.get(mode, MODE_INSTRUCTIONS["default"])
        messages.append(("system", mode_instruction))
        messages.append(("human", state.current_input))

        return ChatPromptTemplate.from_messages(messages)
