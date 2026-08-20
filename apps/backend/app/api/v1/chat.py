import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.v1.schemas import ChatRequest
from app.services import agent_service

chat_router = APIRouter()

logger = logging.getLogger(__name__)


def _stream_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


@chat_router.post("/chat/message")
async def chat_message(request: Request, body: ChatRequest):
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="content 不能为空")
    session_id = body.session_id or str(uuid.uuid4())
    new_session = body.session_id is None

    async def generate():
        try:
            async for token in agent_service.stream_chat(session_id, "default-user", body.content):
                yield _stream_json({"delta": token})
        except Exception:
            logger.exception("LLM 流式回答失败")
            yield _stream_json({"detail": "LLM 调用失败"})
            return
        yield _stream_json({"done": True, "session_id": session_id})

    headers = {"X-Session-Id": session_id}
    if new_session:
        headers["X-Session-New"] = "true"
    return StreamingResponse(generate(), media_type="application/x-ndjson", headers=headers)
