"""API-006 产品级洞察读接口：零 repositories，空列表不 500。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.v1.auth import require_user
from app.services.insights import query as insights_query

insights_router = APIRouter(prefix="/insights", tags=["insights"])


class InsightEvidence(BaseModel):
    memory_id: str
    weight: float
    content: str | None = None
    memory_type: str | None = None
    status: str


class InsightSourceRef(BaseModel):
    kind: str
    ref: str
    label: str


class InsightOut(BaseModel):
    id: str
    domain: str
    headline: str
    narrative: str
    evidence: list[InsightEvidence] = []
    source_refs: list[InsightSourceRef] = []
    generated_at: str | None = None
    confidence: float | None = None


class InsightListResponse(BaseModel):
    items: list[InsightOut]
    domain: str
    generated_at: str


@insights_router.get("", response_model=InsightListResponse)
def list_insights(
    domain: Literal["ledger", "health", "home"] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    user_id: str = Depends(require_user),
):
    items = insights_query.list_insights(user_id, domain=domain, limit=limit)
    return InsightListResponse(
        items=[
            InsightOut(
                id=i.id,
                domain=i.domain,
                headline=i.headline,
                narrative=i.narrative,
                evidence=[
                    InsightEvidence(
                        memory_id=e.memory_id,
                        weight=e.weight,
                        content=e.content,
                        memory_type=e.memory_type,
                        status=e.status,
                    )
                    for e in i.evidence
                ],
                source_refs=[InsightSourceRef(**r) for r in i.source_refs],
                generated_at=i.generated_at or None,
                confidence=i.confidence,
            )
            for i in items
        ],
        domain=domain or "home",
        generated_at=datetime.now().isoformat(),
    )
