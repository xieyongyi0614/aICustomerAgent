"""API-007 产品级记忆读写：只含 active 且未 forgotten（D5）。

分层：本模块零 `app.repositories` / `app.core.db` / langchain 依赖，读写一律经
`services/memory2/product_view.py`（记忆域唯一写面的一部分）。

PATCH 响应直接回 `MemoryProductItemOut`：其 `last_updated` 即本次 `updated_at`，
与 §4.1.6 要求的「item + updated_at」等价，故不额外增模型。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.auth import require_user
from app.api.v1.schemas import (
    MemoryEditIn,
    MemoryForgetOut,
    MemoryGroupOut,
    MemoryItemsOut,
    MemoryProductItemOut,
    MemoryReceiptOut,
)
from app.services.memory2 import product_view

memory_router = APIRouter(prefix="/memory", tags=["memory"])

_OWNERSHIP_DETAIL = "不得读写他人数据"
_NOT_FOUND_DETAIL = "memory not found"


def _item_out(item: product_view.ProductMemoryItem) -> MemoryProductItemOut:
    return MemoryProductItemOut(
        id=item.id,
        kind=item.kind,
        type=item.type,
        type_label=item.type_label,
        content=item.content,
        source_kind=item.source_kind,
        source_label=item.source_label,
        source_count=item.source_count,
        last_updated=item.last_updated,
        usage_receipts=[
            MemoryReceiptOut(
                kind=receipt.kind, label=receipt.label, ts=receipt.ts, ref=receipt.ref
            )
            for receipt in item.usage_receipts
        ],
    )


@memory_router.get("/items", response_model=MemoryItemsOut)
def list_items(
    limit: int = Query(default=200, ge=1, le=200),
    user_id: str = Depends(require_user),
):
    result = product_view.list_product_memories(user_id, limit=limit)
    return MemoryItemsOut(
        generated_at=result.generated_at,
        total=result.total,
        added_this_week=result.added_this_week,
        groups=[
            MemoryGroupOut(
                kind=group.kind,
                label=group.label,
                items=[_item_out(item) for item in group.items],
            )
            for group in result.groups
        ],
        degraded=result.degraded,
    )


@memory_router.patch("/items/{memory_id}", response_model=MemoryProductItemOut)
def update_item(
    memory_id: str,
    body: MemoryEditIn,
    user_id: str = Depends(require_user),
):
    try:
        item = product_view.edit_memory(
            memory_id,
            user_id,
            content=body.content,
            importance=body.importance,
        )
    except product_view.MemoryForbiddenError:
        raise HTTPException(status_code=403, detail=_OWNERSHIP_DETAIL) from None
    except product_view.MemoryNotFoundError:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL) from None
    return _item_out(item)


@memory_router.post("/items/{memory_id}/forget", response_model=MemoryForgetOut)
def forget_item(
    memory_id: str,
    user_id: str = Depends(require_user),
):
    try:
        forgotten_at = product_view.forget_memory_for_user(memory_id, user_id)
    except product_view.MemoryForbiddenError:
        raise HTTPException(status_code=403, detail=_OWNERSHIP_DETAIL) from None
    except product_view.MemoryNotFoundError:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_DETAIL) from None
    return MemoryForgetOut(id=memory_id, forgotten_at=forgotten_at)
