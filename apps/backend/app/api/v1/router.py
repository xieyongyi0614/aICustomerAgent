from fastapi import APIRouter
from app.api.v1 import (
    app_release,
    auth,
    briefing,
    car,
    chat,
    debug,
    governance,
    history,
    home,
    insights,
    ledger,
    llm,
    memory,
    plans,
    proactive,
    tasks,
)
from app.api.v1.feishu import feishu_ingress_router, feishu_router

api_router = APIRouter()
api_router.include_router(chat.chat_router)
api_router.include_router(debug.debug_router)
api_router.include_router(feishu_router)
api_router.include_router(feishu_ingress_router)
api_router.include_router(history.history_router)
api_router.include_router(llm.llm_router)
api_router.include_router(proactive.proactive_router)
api_router.include_router(governance.governance_router)
api_router.include_router(ledger.ledger_router)
api_router.include_router(tasks.tasks_router)
api_router.include_router(insights.insights_router)
api_router.include_router(memory.memory_router)
api_router.include_router(home.home_router)
api_router.include_router(briefing.briefing_router)
api_router.include_router(car.car_router)
api_router.include_router(auth.auth_router)
api_router.include_router(plans.plans_router)
api_router.include_router(app_release.app_release_router)
