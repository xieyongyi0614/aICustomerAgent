"""API-005 任务域：零 repositories 依赖，只做表现。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.settings import get_settings
from app.services.tasks import task_service

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


def _user_id() -> str:
    return get_settings().default_user


@tasks_router.get("", response_model=list[TaskOut])
def list_tasks():
    return task_service.list_open(_user_id())


@tasks_router.post("", response_model=TaskOut)
def create_task(body: TaskCreateRequest):
    row = task_service.create(
        _user_id(),
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
    )


@tasks_router.patch("/{task_id}", response_model=TaskOut)
def patch_task(task_id: str, body: TaskPatchRequest):
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
    )


@tasks_router.post("/{task_id}/complete", response_model=TaskOut)
def complete_task(task_id: str):
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
    )


@tasks_router.post("/{task_id}/reopen", response_model=TaskOut)
def reopen_task(task_id: str):
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
    )


@tasks_router.delete("/{task_id}")
def delete_task(task_id: str):
    row = task_service.delete(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"ok": True}
