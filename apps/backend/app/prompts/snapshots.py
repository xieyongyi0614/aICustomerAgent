from app.core.settings import get_settings
from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage


def format_character(character: CharacterState) -> str:
    topic = character.current_topic or "暂无明确话题"
    return (
        f"心情：{character.mood}；精力：{character.energy:.2f}；"
        f"最近话题：{topic}；内心：{character.inner_state}"
    )


def format_recent_context(messages: list[ChatMessage]) -> str:
    limit = get_settings().analysis_recent_messages
    lines = []
    for message in messages[-limit:]:
        speaker = "用户" if message.role == "human" else "亚丝娜"
        lines.append(f"{speaker}：{message.content}")
    return "\n".join(lines) if lines else "（无历史对话）"
