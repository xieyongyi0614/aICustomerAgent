from app.models.conversation import ConversationState
from app.services import conversation_service
from app.services import memory_service
from app.services import summary_service


async def build(session_id: str, user_id: str, current_input: str) -> ConversationState:
    if not current_input:
        raise ValueError("current_input 必填")
    conversation_service.ensure_conversation(session_id, user_id)
    messages = conversation_service.load_window(session_id)
    current = summary_service.get_summary(session_id)
    summary = current.summary if current else None
    memories = memory_service.retrieve(user_id, current_input)
    return ConversationState(
        session_id=session_id,
        user_id=user_id,
        messages=messages,
        summary=summary,
        memories=memories,
        current_input=current_input,
    )
