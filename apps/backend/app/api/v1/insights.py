"""API-006 产品级洞察读接口：零 repositories，空列表不 500。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.settings import get_settings

insights_router = APIRouter(prefix="/insights", tags=["insights"])


class InsightEvidence(BaseModel):
    label: str
    value: str


class InsightOut(BaseModel):
    id: str
    domain: str
    headline: str
    narrative: str
    evidence: list[InsightEvidence] = []
    source_refs: list[str] = []
    generated_at: str | None = None


@insights_router.get("", response_model=list[InsightOut])
def list_insights(
    domain: Literal["ledger", "health", "home"] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
):
    # V1：无预生成洞察时返回空列表（不 500）；AI 叙事优先由首页聚合与简报承载
    _ = get_settings().default_user
    return []
