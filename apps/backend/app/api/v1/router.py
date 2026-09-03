from fastapi import APIRouter
from app.api.v1 import action, chat, debug, history, llm, proactive, state, world

api_router = APIRouter()
api_router.include_router(chat.chat_router)
api_router.include_router(debug.debug_router)
api_router.include_router(action.action_router)
api_router.include_router(state.state_router)
api_router.include_router(history.history_router)
api_router.include_router(llm.llm_router)
api_router.include_router(proactive.proactive_router)
api_router.include_router(world.world_router)
