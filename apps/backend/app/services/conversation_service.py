from app.core.settings import get_settings
from app.models.conversation import ChatMessage
from app.repositories import conversation_repository as repo


def ensure_conversation(session_id: str, user_id: str):
    return repo.get_or_create_conversation(session_id, user_id)


def find_conversation(session_id: str):
    return repo.find_conversation(session_id)


def load_window(
    session_id: str, max_messages: int | None = None, max_chars: int | None = None
) -> list[ChatMessage]:
    settings = get_settings()
    limit = max_messages or settings.conversation_max_messages
    char_budget = max_chars or settings.conversation_max_chars
    messages = repo.get_recent_messages(session_id, limit)
    result = [ChatMessage(role=m.role, content=m.content) for m in messages]
    total = sum(len(m.content) for m in result)
    while result and total > char_budget:
        dropped = result.pop(0)
        total -= len(dropped.content)
    return result


def save_turn(
    session_id: str,
    user_message: str,
    ai_reply: str,
    mode_write_back: str | None = None,
) -> int:
    repo.save_message(session_id, "human", user_message)
    ai_message = repo.save_message(session_id, "ai", ai_reply)
    if mode_write_back is not None:
        repo.update_mode(session_id, mode_write_back)
    return ai_message.id


def message_count(session_id: str) -> int:
    return repo.count_messages(session_id)
