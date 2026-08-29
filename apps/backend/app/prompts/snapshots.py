from app.core.settings import get_settings
from app.models.character_state import CharacterState
from app.models.conversation import ChatMessage
from app.models.relationship import RelationshipState


def format_character(character: CharacterState) -> str:
    topic = character.current_topic or "暂无明确话题"
    return (
        f"心情：{character.mood}；精力：{character.energy:.2f}；"
        f"最近话题：{topic}；内心：{character.inner_state}"
    )


def format_relationship(relationship: RelationshipState) -> str:
    return (
        f"亲密 {relationship.intimacy:.2f}；信任 {relationship.trust:.2f}；"
        f"熟悉 {relationship.familiarity:.2f}；紧张 {relationship.tension:.2f}"
        f"（{relationship.stage}）"
    )


def format_scene_summary(scene_state) -> str:
    if scene_state is None:
        return "暂无场景信息"
    parts = []
    if scene_state.location:
        parts.append(f"地点：{scene_state.location}")
    if scene_state.current_activity:
        parts.append(f"活动：{scene_state.current_activity}")
    pending = scene_state.pending_action
    if pending is not None and pending.status == "pending":
        parts.append(f"待完成动作：{pending.action}")
    else:
        parts.append("无待完成动作")
    return "；".join(parts)


def format_memory_snapshot(memories) -> str:
    top = memories[:2]
    if not top:
        return "暂无相关记忆"
    return "\n".join(f"- {memory.content}" for memory in top)


def format_recent_context(messages: list[ChatMessage]) -> str:
    limit = get_settings().analysis_recent_messages
    lines = []
    for message in messages[-limit:]:
        speaker = "用户" if message.role == "human" else "亚丝娜"
        lines.append(f"{speaker}：{message.content}")
    return "\n".join(lines) if lines else "（无历史对话）"
