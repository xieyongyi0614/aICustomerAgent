import json
import logging
import uuid

import openai
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.api.v1.deps import get_chat_llm
from app.api.v1.schemas import ChatRequest
from app.services import agent_service
from app.services.agent_service import EmptyLLMResponseError

chat_router = APIRouter()

logger = logging.getLogger(__name__)


def _stream_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _llm_error(exc: openai.APIStatusError) -> dict:
    body_error = exc.body.get("error") if isinstance(exc.body, dict) else None
    if isinstance(body_error, dict):
        return {
            "status": exc.status_code,
            "code": body_error.get("code"),
            "message": body_error.get("message"),
        }
    return {"status": exc.status_code, "message": str(exc)}


@chat_router.post("/chat/message")
async def chat_message(
    request: Request,
    body: ChatRequest,
    llm=Depends(get_chat_llm),
):
    if not body.content.strip():
        raise HTTPException(status_code=422, detail="content 不能为空")
    session_id = body.session_id or str(uuid.uuid4())
    new_session = body.session_id is None

    async def generate():
        try:
            async for token in agent_service.stream_chat(
                session_id, "default-user", body.content, llm=llm
            ):
                yield _stream_json({"delta": token})
        except openai.APIStatusError as exc:
            logger.exception("LLM 流式回答失败")
            yield _stream_json({"detail": "LLM 调用失败", "error": _llm_error(exc)})
            return
        except EmptyLLMResponseError:
            logger.exception("LLM 流式回答失败")
            yield _stream_json({"detail": "LLM 返回空响应，请检查模型服务商状态或额度"})
            return
        except Exception:
            logger.exception("LLM 流式回答失败")
            yield _stream_json({"detail": "LLM 调用失败"})
            return
        yield _stream_json({"done": True, "session_id": session_id})

    headers = {"X-Session-Id": session_id}
    if new_session:
        headers["X-Session-New"] = "true"
    return StreamingResponse(
        generate(), media_type="application/x-ndjson", headers=headers
    )
