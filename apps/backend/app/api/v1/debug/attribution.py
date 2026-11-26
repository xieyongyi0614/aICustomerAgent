"""归因域调试端点：记忆 / 候选 / 洞察 / 发展状态归因 + 发展清单 + 反思运行。"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.auth import require_user
from app.api.v1.deps import debug_surface_gate
from app.services.development import attribution as development_attribution
from app.services.memory import attribution as memory_attribution
from app.services.reflection import attribution as reflection_attribution

attribution_router = APIRouter(
    dependencies=[Depends(debug_surface_gate), Depends(require_user)], tags=["debug"]
)


@attribution_router.get("/debug/memory/{memory_id}/attribution")
def get_memory_attribution(memory_id: str):
    view = memory_attribution.memory_attribution(memory_id)
    if view is None:
        raise HTTPException(status_code=404, detail="memory 不存在")
    return view


@attribution_router.get("/debug/candidate/{candidate_id}/attribution")
def get_candidate_attribution(candidate_id: str):
    view = memory_attribution.candidate_attribution(candidate_id)
    if view is None:
        raise HTTPException(status_code=404, detail="candidate 不存在")
    return view


@attribution_router.get("/debug/insights/{insight_id}/attribution")
def get_insight_attribution(insight_id: str):
    view = reflection_attribution.insight_attribution(insight_id)
    if view is None:
        raise HTTPException(status_code=404, detail="insight 不存在")
    return view


@attribution_router.get("/debug/development/states/{state_id}")
def get_development_state_attribution(state_id: str):
    view = development_attribution.development_state_attribution(state_id)
    if view is None:
        raise HTTPException(status_code=404, detail="development state 不存在")
    return view


@attribution_router.get("/debug/development/users/{user_id}")
def list_user_development(user_id: str, limit: int = 50):
    return development_attribution.list_user_development(user_id, limit=limit)


@attribution_router.get("/debug/reflection-runs")
def list_reflection_runs(user_id: str | None = None, limit: int = 50):
    return reflection_attribution.list_reflection_runs(user_id, limit=limit)
