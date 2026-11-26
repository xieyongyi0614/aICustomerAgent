from __future__ import annotations

from datetime import datetime, timedelta

from app.repositories import life_task_repository

DOUBLE_SUBMIT_WINDOW = timedelta(seconds=2)


def _order_reason(task) -> str:
    if task.kind == "memo":
        return "备忘录 · AI 已整理"
    if task.remind_at is not None:
        return f"{task.remind_at.strftime('%H:%M')} 提醒"
    if task.due_date:
        return task.due_date
    return "AI 已排序"


def create(user_id: str, title: str, **kwargs):
    kind = kwargs.get("kind") or "task"
    duplicate = life_task_repository.find_recent_open_duplicate(
        user_id,
        title=title,
        kind=kind,
        within=DOUBLE_SUBMIT_WINDOW,
    )
    if duplicate is not None:
        return duplicate
    row = life_task_repository.create_task(user_id, title, **kwargs)
    if row.order_reason is None:
        row = life_task_repository.update_task(row.id, order_reason=_order_reason(row))
    return row


def list_open(user_id: str):
    return list_tasks(user_id, status="open")


def list_tasks(
    user_id: str, *, status: str = "open", kind: str | None = None
):
    rows = life_task_repository.list_tasks(
        user_id,
        status=None if status == "all" else status,
        kind=kind,
    )
    if status == "all":
        # delete 是软删（cancelled）：'all' 指开放 + 已完成，不含已取消。
        rows = [r for r in rows if r.status != "cancelled"]
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
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
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
