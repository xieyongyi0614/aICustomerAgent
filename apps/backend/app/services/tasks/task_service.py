from __future__ import annotations

from datetime import datetime

from app.repositories import life_task_repository


def _order_reason(task) -> str:
    if task.kind == "memo":
        return "备忘录 · AI 已整理"
    if task.remind_at is not None:
        return f"{task.remind_at.strftime('%H:%M')} 提醒"
    if task.due_date:
        return task.due_date
    return "AI 已排序"


def create(user_id: str, title: str, **kwargs):
    row = life_task_repository.create_task(user_id, title, **kwargs)
    if row.order_reason is None:
        row = life_task_repository.update_task(row.id, order_reason=_order_reason(row))
    return row


def list_open(user_id: str):
    rows = life_task_repository.list_tasks(user_id, status="open")
    return [
        {
            "id": r.id,
            "title": r.title,
            "kind": r.kind,
            "status": r.status,
            "tag": r.tag,
            "note": r.note,
            "order_reason": r.order_reason or _order_reason(r),
            "remind_at": r.remind_at.isoformat() if r.remind_at else None,
            "due_date": r.due_date,
        }
        for r in rows
    ]


def complete(task_id: str):
    return life_task_repository.set_status(task_id, "done")


def reopen(task_id: str):
    return life_task_repository.set_status(task_id, "open")


def delete(task_id: str):
    return life_task_repository.set_status(task_id, "cancelled")


def update(task_id: str, **fields):
    return life_task_repository.update_task(task_id, **fields)


def memo_count(user_id: str) -> int:
    return len(life_task_repository.list_tasks(user_id, kind="memo", status="open"))
