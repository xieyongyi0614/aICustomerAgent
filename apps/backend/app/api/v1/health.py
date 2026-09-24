"""API-009/010 健康域骨架（M4 门控：PLT-001 未通过前仅提供空读面）。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

health_router = APIRouter(prefix="/health", tags=["health"])


class HealthScoreOut(BaseModel):
    authorized: bool = False
    score: int | None = None
    narrative: str | None = None
    disclaimer: str = "非医疗建议，请咨询医生"


@health_router.get("/score", response_model=HealthScoreOut)
def health_score():
    return HealthScoreOut(narrative="连接手环后这里会显示状态解读")


class HealthSyncRequest(BaseModel):
    source: str
    payload: dict


@health_router.post("/sync")
def health_sync(body: HealthSyncRequest):
    # 幂等 ingest 骨架；M4 门控后实现
    return {"ok": True, "accepted": 0}
