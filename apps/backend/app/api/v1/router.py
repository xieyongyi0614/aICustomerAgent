from fastapi import APIRouter
from app.api.v1 import chat, debug, history, state

api_router = APIRouter()
api_router.include_router(chat.chat_router)
api_router.include_router(debug.debug_router)
api_router.include_router(state.state_router)
api_router.include_router(history.history_router)
