from datetime import datetime

from app.core.db import Conversation, Message, SessionLocal


def get_or_create_conversation(conv_id: str, user_id: str) -> Conversation:
    with SessionLocal() as session:
        conversation = session.get(Conversation, conv_id)
        if conversation is None:
            now = datetime.now()
            conversation = Conversation(
                id=conv_id, user_id=user_id, created_at=now, updated_at=now
            )
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
        return conversation


def save_message(conv_id: str, role: str, content: str) -> Message:
    if role not in ("human", "ai"):
        raise ValueError(f"非法 role: {role}")
    with SessionLocal() as session:
        message = Message(
            conversation_id=conv_id,
            role=role,
            content=content,
            created_at=datetime.now(),
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        return message


def get_recent_messages(conv_id: str, limit: int) -> list[Message]:
    with SessionLocal() as session:
        rows = (
            session.query(Message)
            .filter(Message.conversation_id == conv_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(rows))


def count_messages(conv_id: str) -> int:
    with SessionLocal() as session:
        return (
            session.query(Message)
            .filter(Message.conversation_id == conv_id)
            .count()
        )


def touch_conversation(conv_id: str) -> None:
    with SessionLocal() as session:
        conversation = session.get(Conversation, conv_id)
        if conversation is not None:
            conversation.updated_at = datetime.now()
            session.commit()
