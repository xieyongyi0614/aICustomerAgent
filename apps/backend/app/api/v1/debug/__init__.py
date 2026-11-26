"""调试面路由包：按域拆分（tools / attribution / observability / relationship / plans / action / action_execution / world / state）。

门禁与归类台账：`docs/current-system-architecture-baseline.md` §10.17（ADR-16 §7 调试面）。
"""

from fastapi import APIRouter

from app.api.v1.debug import (
    action,
    action_execution,
    attribution,
    observability,
    plans,
    relationship,
    state,
    tools,
    world,
)

debug_router = APIRouter()
debug_router.include_router(tools.tools_router)
debug_router.include_router(attribution.attribution_router)
debug_router.include_router(observability.observability_router)
debug_router.include_router(relationship.relationship_router)
debug_router.include_router(plans.plans_router)
debug_router.include_router(action.action_router)
debug_router.include_router(action_execution.action_execution_router)
debug_router.include_router(world.world_router)
debug_router.include_router(state.state_router)
