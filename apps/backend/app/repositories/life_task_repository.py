from __future__ import annotations

from datetime import datetime

from app.core import ids
from app.core.db import LifeTaskRow, SessionLocal


def create_task(
    user_id: str,
    title: str,
    *,
    kind: str = "task",
    tag: str | None = None,
    note: str | None = None,
    order_reason: str | None = None,
    remind_at: datetime | None = None,
    due_date: str | None = None,
    now: datetime | None = None,
) -> LifeTaskRow:
    timestamp = now or datetime.now()
    row = LifeTaskRow(
        id=ids.new_id_str(),
        user_id=user_id,
        title=title,
        kind=kind,
        status="open",
        tag=tag,
        note=note,
        order_reason=order_reason,
        remind_at=remind_at,
        due_date=due_date,
        created_at=timestamp,
        updated_at=timestamp,
    )
    with SessionLocal() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def get_task(task_id: str) -> LifeTaskRow | None:
    with SessionLocal() as session:
        return session.get(LifeTaskRow, task_id)


def list_tasks(user_id: str, *, status: str | None = None, kind: str | None = None):
    with SessionLocal() as session:
        query = session.query(LifeTaskRow).filter(LifeTaskRow.user_id == user_id)
        if status is not None:
            query = query.filter(LifeTaskRow.status == status)
        if kind is not None:
            query = query.filter(LifeTaskRow.kind == kind)
        rows = query.order_by(LifeTaskRow.created_at.desc()).all()
        for row in rows:
            session.expunge(row)
        return rows


def update_task(task_id: str, **fields) -> LifeTaskRow | None:
    with SessionLocal() as session:
        row = session.get(LifeTaskRow, task_id)
        if row is None:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(row, key):
                setattr(row, key, value)
        row.updated_at = datetime.now()
        session.commit()
        session.refresh(row)
        session.expunge(row)
        return row


def set_status(task_id: str, status: str) -> LifeTaskRow | None:
    return update_task(task_id, status=status, completed_at=datetime.now() if status == "done" else None)


def list_due_reminders(user_id: str, now: datetime | None = None):
    moment = now or datetime.now()
    with SessionLocal() as session:
        rows = (
            session.query(LifeTaskRow)
            .filter(
                LifeTaskRow.user_id == user_id,
                LifeTaskRow.status == "open",
                LifeTaskRow.remind_at.isnot(None),
                LifeTaskRow.remind_at <= moment,
            )
            .all()
        )
        for row in rows:
            session.expunge(row)
        return rows
