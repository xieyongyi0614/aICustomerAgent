from fastapi import APIRouter

chat_router = APIRouter()


@chat_router.get("/chat/message")
async def create_chat_message(content: str):
    return {"message": f"endpoint 待 V1 任务重建，已收到：{content}"}
