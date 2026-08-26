from fastapi import APIRouter
from app.api.v1 import chat, debug

api_router = APIRouter()
api_router.include_router(chat.chat_router)
api_router.include_router(debug.debug_router)
