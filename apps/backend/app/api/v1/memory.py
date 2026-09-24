"""API-007 产品级记忆读写：只含 active 且未 forgotten。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.settings import get_settings
from app.repositories import memory_repository

memory_router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryItemOut(BaseModel):
    id: str
    kind: str
    label: str
    content: str
    source_kind: str | None = None
    source_count: int | None = None
    last_updated: str | None = None
    usage_receipts: list[str] = []


class MemoryUpdateRequest(BaseModel):
    content: str | None = None


def _out(row) -> MemoryItemOut:
    return MemoryItemOut(
        id=row.id,
        kind=row.type,
        label=(row.content or "")[:12],
        content=row.content,
        source_kind=row.source,
        last_updated=row.updated_at.isoformat() if row.updated_at else None,
    )


@memory_router.get("/items", response_model=list[MemoryItemOut])
def list_items(limit: int = 50):
    user_id = get_settings().default_user
    rows = memory_repository.list_by_user(user_id, limit=limit)
    return [_out(r) for r in rows if getattr(r, "status", "active") == "active"]


@memory_router.patch("/items/{memory_id}", response_model=MemoryItemOut)
def update_item(memory_id: str, body: MemoryUpdateRequest):
    if body.content is None:
        row = memory_repository.get_memory(memory_id)
    else:
        row = memory_repository.update_memory_content(memory_id, body.content)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return _out(row)


@memory_router.post("/items/{memory_id}/forget")
def forget_item(memory_id: str):
    row = memory_repository.get_memory(memory_id)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    memory_repository.forget_memory(memory_id)
    return {"ok": True, "forgotten_at": datetime.now().isoformat()}
