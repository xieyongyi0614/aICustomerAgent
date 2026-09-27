from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.auth import require_user
from app.api.v1.schemas import (
    ConversationMessagesOut,
    MemoriesOut,
    MemoryItemOut,
    MessageItemOut,
)
from app.services import history_service

history_router = APIRouter()

DEFAULT_MESSAGES_LIMIT = 200
MAX_MESSAGES_LIMIT = 500


@history_router.get(
    "/conversations/latest",
    response_model=ConversationMessagesOut,
)
def latest_conversation_messages(
    user_id: str = Depends(require_user),
    limit: int = Query(default=DEFAULT_MESSAGES_LIMIT, ge=1, le=MAX_MESSAGES_LIMIT),
):
    conversation = history_service.find_latest_conversation(user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="暂无历史会话")
    rows = history_service.list_recent_messages(conversation.id, limit)
    return ConversationMessagesOut(
        conversation_id=conversation.id,
        messages=[
            MessageItemOut(
                id=row.id,
                role=row.role,
                content=row.content,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@history_router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesOut,
)
def list_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=DEFAULT_MESSAGES_LIMIT, ge=1, le=MAX_MESSAGES_LIMIT),
    before_id: int | None = Query(default=None),
    user_id: str = Depends(require_user),
):
    conversation = history_service.find_conversation_or_none(conversation_id)
    if conversation is None or getattr(conversation, "user_id", None) != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = history_service.list_recent_messages(
        conversation_id, limit, before_id=before_id
    )
    return ConversationMessagesOut(
        conversation_id=conversation_id,
        messages=[
            MessageItemOut(
                id=row.id,
                role=row.role,
                content=row.content,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@history_router.get("/memories", response_model=MemoriesOut)
def list_memories(
    user_id: str = Depends(require_user),
    limit: int = Query(default=50, ge=1, le=200),
):
    items = history_service.list_memories(user_id, limit=limit)
    return MemoriesOut(
        user_id=user_id,
        memories=[
            MemoryItemOut(
                id=item.id,
                user_id=item.user_id,
                memory=item.content,
                memory_type=item.type,
                type=item.type,
                importance=item.importance,
                created_at=item.created_at,
                updated_at=item.updated_at,
                character_id=item.character_id,
                confidence=item.confidence,
                source=item.source,
                status=item.status,
                superseded_by=item.superseded_by,
            )
            for item in items
        ],
    )
