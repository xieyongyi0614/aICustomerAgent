from fastapi import APIRouter
from app.api.v1 import (
    action,
    action_execution,
    auth,
    brief,
    chat,
    debug,
    governance,
    health,
    history,
    home,
    insights,
    ledger,
    llm,
    memory,
    proactive,
    state,
    tasks,
    world,
)
from app.api.v1.feishu import feishu_ingress_router, feishu_router

api_router = APIRouter()
api_router.include_router(chat.chat_router)
api_router.include_router(debug.debug_router)
api_router.include_router(feishu_router)
api_router.include_router(feishu_ingress_router)
api_router.include_router(action.action_router)
api_router.include_router(action_execution.action_execution_router)
api_router.include_router(state.state_router)
api_router.include_router(history.history_router)
api_router.include_router(llm.llm_router)
api_router.include_router(proactive.proactive_router)
api_router.include_router(world.world_router)
api_router.include_router(governance.governance_router)
api_router.include_router(ledger.ledger_router)
api_router.include_router(tasks.tasks_router)
api_router.include_router(insights.insights_router)
api_router.include_router(memory.memory_router)
api_router.include_router(home.home_router)
api_router.include_router(brief.brief_router)
api_router.include_router(auth.auth_router)
api_router.include_router(health.health_router)
