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


@memory_router.get("/items", response_model=list[MemoryItemOut])
def list_items(limit: int = 50):
    user_id = get_settings().default_user
    rows = memory_repository.list_by_user(user_id, limit=limit)
    out = []
    for r in rows:
        if getattr(r, "status", "active") != "active":
            continue
        out.append(
            MemoryItemOut(
                id=r.id,
                kind=r.type,
                label=(r.content or "")[:12],
                content=r.content,
                source_kind=r.source,
                last_updated=r.updated_at.isoformat() if r.updated_at else None,
            )
        )
    return out


@memory_router.patch("/items/{memory_id}", response_model=MemoryItemOut)
def update_item(memory_id: str, body: MemoryUpdateRequest):
    user_id = get_settings().default_user
    if body.content is not None:
        row = memory_repository.update_content(memory_id, body.content) if hasattr(
            memory_repository, "update_content"
        ) else None
        if row is None:
            # 降级：读回再写
            existing = memory_repository.get_memory(memory_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="memory not found")
            raise HTTPException(status_code=501, detail="edit not wired")
    else:
        row = memory_repository.get_memory(memory_id)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return MemoryItemOut(
        id=row.id,
        kind=row.type,
        label=(row.content or "")[:12],
        content=row.content,
        source_kind=row.source,
        last_updated=row.updated_at.isoformat() if row.updated_at else None,
    )


@memory_router.post("/items/{memory_id}/forget")
def forget_item(memory_id: str):
    row = memory_repository.get_memory(memory_id)
    if row is None:
        raise HTTPException(status_code=404, detail="memory not found")
    # 遗忘：置 status=invalidated（可审计，不物理删）
    if hasattr(memory_repository, "set_status"):
        memory_repository.set_status(memory_id, "invalidated")
    else:
        raise HTTPException(status_code=501, detail="forget not wired")
    return {"ok": True, "forgotten_at": datetime.now().isoformat()}
