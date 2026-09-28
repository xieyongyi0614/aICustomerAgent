from datetime import datetime

from app.core.db import SessionLocal, UserRow


def get(user_id: str) -> UserRow | None:
    with SessionLocal() as session:
        return session.get(UserRow, user_id)


def get_by_email(email: str) -> UserRow | None:
    normalized = email.strip().lower()
    with SessionLocal() as session:
        row = (
            session.query(UserRow)
            .filter(UserRow.email == normalized)
            .one_or_none()
        )
        if row is not None:
            session.expunge(row)
        return row


def create_with_email(
    user_id: str,
    email: str,
    *,
    display_name: str | None = None,
    now: datetime | None = None,
) -> UserRow:
    normalized = email.strip().lower()
    timestamp = now or datetime.now()
    with SessionLocal() as session:
        row = UserRow(
            id=user_id,
            email=normalized,
            display_name=display_name,
            status="active",
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(row)
        try:
            session.commit()
        except Exception:
            session.rollback()
            existing = (
                session.query(UserRow)
                .filter(UserRow.email == normalized)
                .one_or_none()
            )
            if existing is not None:
                session.expunge(existing)
                return existing
            raise
        session.refresh(row)
        session.expunge(row)
        return row


def list_all(limit: int | None = None) -> list[UserRow]:
    with SessionLocal() as session:
        query = session.query(UserRow).order_by(UserRow.created_at)
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()
        for row in rows:
            session.expunge(row)
        return rows


def exists(user_id: str) -> bool:
    with SessionLocal() as session:
        return session.get(UserRow, user_id) is not None
