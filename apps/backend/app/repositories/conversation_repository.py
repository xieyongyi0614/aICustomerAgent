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


def find_conversation(conv_id: str) -> Conversation | None:
    with SessionLocal() as session:
        return session.get(Conversation, conv_id)


def get_latest_for_user(user_id: str) -> Conversation | None:
    with SessionLocal() as session:
        return (
            session.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .first()
        )


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


def get_recent_messages(
    conv_id: str, limit: int, before_id: int | None = None
) -> list[Message]:
    with SessionLocal() as session:
        query = session.query(Message).filter(Message.conversation_id == conv_id)
        if before_id is not None:
            query = query.filter(Message.id < before_id)
        rows = query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit).all()
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


def update_mode(conv_id: str, mode: str) -> None:
    with SessionLocal() as session:
        conversation = session.get(Conversation, conv_id)
        if conversation is not None:
            now = datetime.now()
            conversation.mode = mode
            conversation.mode_entered_at = now
            conversation.updated_at = now
            session.commit()
