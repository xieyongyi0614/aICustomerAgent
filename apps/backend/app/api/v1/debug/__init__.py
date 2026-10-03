"""调试面路由包：按域拆分（tools / attribution / observability / relationship / plans）。

门禁与归类台账：`docs/refactor/debug-surface-audit.md`（ADR-16 §7 调试面）。
"""

from fastapi import APIRouter

from app.api.v1.debug import attribution, observability, plans, relationship, tools

debug_router = APIRouter()
debug_router.include_router(tools.tools_router)
debug_router.include_router(attribution.attribution_router)
debug_router.include_router(observability.observability_router)
debug_router.include_router(relationship.relationship_router)
debug_router.include_router(plans.plans_router)
