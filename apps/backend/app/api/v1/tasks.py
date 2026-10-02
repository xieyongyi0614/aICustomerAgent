"""API-005 任务域：零 repositories 依赖，只做表现。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.v1.auth import require_user
from app.services.life import tasks as task_service

tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    kind: Literal["task", "memo"] = "task"
    tag: str | None = None
    note: str | None = None
    remind_at: datetime | None = None
    due_date: str | None = None


class TaskPatchRequest(BaseModel):
    title: str | None = None
    tag: str | None = None
    note: str | None = None
    remind_at: datetime | None = None
    due_date: str | None = None


class TaskOut(BaseModel):
    id: str
    title: str
    kind: str
    status: str
    tag: str | None = None
    note: str | None = None
    order_reason: str | None = None
    remind_at: str | None = None
    due_date: str | None = None
    completed_at: str | None = None


@tasks_router.get("", response_model=list[TaskOut])
def list_tasks(
    status: Literal["open", "done", "all"] = Query(default="open"),
    user_id: str = Depends(require_user),
):
    # DA-19：日程页需要已完成态（status=all 含 open + done，不含软删 cancelled）。
    return task_service.list_tasks(user_id, status=status)


@tasks_router.post("", response_model=TaskOut)
def create_task(body: TaskCreateRequest, user_id: str = Depends(require_user)):
    row = task_service.create(
        user_id,
        body.title,
        kind=body.kind,
        tag=body.tag,
        note=body.note,
        remind_at=body.remind_at,
        due_date=body.due_date,
    )
    return TaskOut(
        id=row.id,
        title=row.title,
        kind=row.kind,
        status=row.status,
        tag=row.tag,
        note=row.note,
        order_reason=row.order_reason,
        remind_at=row.remind_at.isoformat() if row.remind_at else None,
        due_date=row.due_date,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


@tasks_router.patch("/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: str,
    body: TaskPatchRequest,
    user_id: str = Depends(require_user),
):
    _ = user_id
    row = task_service.update(
        task_id,
        title=body.title,
        tag=body.tag,
        note=body.note,
        remind_at=body.remind_at,
        due_date=body.due_date,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskOut(
        id=row.id,
        title=row.title,
        kind=row.kind,
        status=row.status,
        tag=row.tag,
        note=row.note,
        order_reason=row.order_reason,
        remind_at=row.remind_at.isoformat() if row.remind_at else None,
        due_date=row.due_date,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


@tasks_router.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: str, user_id: str = Depends(require_user)):
    _ = user_id
    row = task_service.complete(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskOut(
        id=row.id,
        title=row.title,
        kind=row.kind,
        status=row.status,
        tag=row.tag,
        note=row.note,
        order_reason=row.order_reason,
        remind_at=row.remind_at.isoformat() if row.remind_at else None,
        due_date=row.due_date,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


@tasks_router.post("/{task_id}/reopen", response_model=TaskOut)
def reopen_task(task_id: str, user_id: str = Depends(require_user)):
    _ = user_id
    row = task_service.reopen(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskOut(
        id=row.id,
        title=row.title,
        kind=row.kind,
        status=row.status,
        tag=row.tag,
        note=row.note,
        order_reason=row.order_reason,
        remind_at=row.remind_at.isoformat() if row.remind_at else None,
        due_date=row.due_date,
        completed_at=row.completed_at.isoformat() if row.completed_at else None,
    )


@tasks_router.delete("/{task_id}")
def delete_task(task_id: str, user_id: str = Depends(require_user)):
    _ = user_id
    row = task_service.delete(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True}
