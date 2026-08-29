"""读路径查询服务：api 层经由本模块访问仓储，不直接操作 repository。"""

from app.core.db import Message
from app.models.memory import UserMemoryV4
from app.repositories import conversation_repository, memory_repository


def list_memories(user_id: str, limit: int = 50) -> list[UserMemoryV4]:
    return memory_repository.list_by_user_v4(user_id, limit=limit)


def find_conversation_or_none(conversation_id: str):
    return conversation_repository.find_conversation(conversation_id)


def list_recent_messages(
    conversation_id: str, limit: int, before_id: int | None = None
) -> list[Message]:
    return conversation_repository.get_recent_messages(
        conversation_id, limit, before_id=before_id
    )
