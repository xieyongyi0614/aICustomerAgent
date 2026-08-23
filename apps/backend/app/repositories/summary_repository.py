from datetime import datetime

from app.core.db import ConversationSummary, SessionLocal


def get_summary(conv_id: str) -> ConversationSummary | None:
    with SessionLocal() as session:
        return session.get(ConversationSummary, conv_id)


def upsert_summary(conv_id: str, summary: str) -> ConversationSummary:
    if not summary:
        raise ValueError("摘要不能为空")
    now = datetime.now()
    with SessionLocal() as session:
        row = session.get(ConversationSummary, conv_id)
        if row is None:
            row = ConversationSummary(
                conversation_id=conv_id,
                summary=summary,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.summary = summary
            row.updated_at = now
        session.commit()
        session.refresh(row)
        return row


def delete_summary(conv_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(ConversationSummary, conv_id)
        if row is not None:
            session.delete(row)
            session.commit()
