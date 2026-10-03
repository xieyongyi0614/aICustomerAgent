from datetime import datetime

from app.core import ids
from app.core.db import Conversation, Message, SessionLocal


def get_or_create_conversation(session_id: str, user_id: str) -> Conversation:
    with SessionLocal() as session:
        conversation = _resolve_conversation(session, session_id)
        if conversation is None:
            now = datetime.now()
            conversation = Conversation(
                id=ids.new_id_str(),
                session_id=session_id,
                user_id=user_id,
                created_at=now,
                updated_at=now,
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
        return conversation


def find_conversation(session_id: str) -> Conversation | None:
    with SessionLocal() as session:
        return (
            session.query(Conversation)
            .filter(Conversation.session_id == session_id)
            .first()
        )


def get_latest_for_user(user_id: str) -> Conversation | None:
    with SessionLocal() as session:
        return (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .first()
        )


def list_user_ids() -> list[str]:
    with SessionLocal() as session:
        rows = session.query(Conversation.user_id).distinct().all()
        return [row.user_id for row in rows]


def save_message(
    conv_id: str, role: str, content: str, is_proactive: bool = False
) -> Message:
    if role not in ("human", "ai"):
        raise ValueError(f"非法 role: {role}")
    with SessionLocal() as session:
        conversation = _resolve_conversation(session, conv_id)
        if conversation is None:
            raise ValueError(f"会话不存在: {conv_id}")
        message = Message(
            id=ids.new_id(),
            conversation_id=conversation.id,
            role=role,
            content=content,
            is_proactive=is_proactive,
            created_at=datetime.now(),
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        return message


def _resolve_conversation(db_session, session_or_id: str) -> Conversation | None:
    """句柄解析：优先 session_id 业务键，回退主键（存量行两者同值）。"""
    conversation = (
        db_session.query(Conversation)
        .filter(Conversation.session_id == session_or_id)
        .first()
    )
    if conversation is None:
        conversation = db_session.get(Conversation, session_or_id)
    return conversation


def get_recent_messages(
    conv_id: str, limit: int, before_id: int | None = None
) -> list[Message]:
    with SessionLocal() as session:
        conversation = _resolve_conversation(session, conv_id)
        if conversation is None:
            return []
        query = session.query(Message).filter(
            Message.conversation_id == conversation.id
        )
        if before_id is not None:
            query = query.filter(Message.id < before_id)
        rows = query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit).all()
        return list(reversed(rows))


def count_messages(conv_id: str) -> int:
    with SessionLocal() as session:
        conversation = _resolve_conversation(session, conv_id)
        if conversation is None:
            return 0
        return (
            session.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .count()
        )


def count_human_messages(conv_id: str) -> int:
    """用户轮次计数（对齐 chat_pipeline current_turn 口径：human 消息数）。"""
    with SessionLocal() as session:
        conversation = _resolve_conversation(session, conv_id)
        if conversation is None:
            return 0
        return (
            session.query(Message)
            .filter(
                Message.conversation_id == conversation.id, Message.role == "human"
            )
            .count()
        )


def list_messages_since(
    cutoff: datetime, limit: int = 20000
) -> list[tuple[str, str]]:
    with SessionLocal() as session:
        rows = (
            session.query(Message.conversation_id, Message.role)
            .filter(Message.created_at >= cutoff)
            .limit(limit)
            .all()
        )
        return [(row.conversation_id, row.role) for row in rows]


def touch_conversation(conv_id: str) -> None:
    with SessionLocal() as session:
        conversation = _resolve_conversation(session, conv_id)
        if conversation is not None:
            conversation.updated_at = datetime.now()
            session.commit()


def update_mode(conv_id: str, mode: str) -> None:
    with SessionLocal() as session:
        conversation = _resolve_conversation(session, conv_id)
        if conversation is not None:
            now = datetime.now()
            conversation.mode = mode
            conversation.mode_entered_at = now
            conversation.updated_at = now
            session.commit()
