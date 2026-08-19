from fastapi import APIRouter
from app.modules.llm.services import llm_chat_open_ai

chat_router = APIRouter()


@chat_router.get("/chat/message")
async def create_chat_message(content: str):
    await llm_chat_open_ai(content)
