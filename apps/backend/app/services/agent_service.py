import asyncio
import logging
from typing import AsyncIterator

from app.chains import answer_chain, router_chain
from app.core.settings import get_settings
from app.services import context_builder, conversation_service, memory_service, summary_service

logger = logging.getLogger(__name__)


class EmptyLLMResponseError(Exception):
    pass


async def stream_chat(session_id: str, user_id: str, content: str, llm=None) -> AsyncIterator[str]:
    state = await context_builder.build(session_id, user_id, content)
    try:
        role_mode = await router_chain.route(content, llm=llm)
        logger.info("路由输出：mode=%s confidence=%s", role_mode.mode, role_mode.confidence)
        mode = role_mode.mode
        if role_mode.confidence < get_settings().router_confidence_threshold:
            logger.warning("路由低置信度(%s)，降级 default：%s", role_mode.confidence, role_mode.reason)
            mode = "default"
    except Exception:
        logger.exception("路由解析失败，降级 default")
        mode = "default"

    full_reply = []
    try:
        async for token in answer_chain.astream(mode, state, llm=llm):
            full_reply.append(token)
            yield token
    except ValueError as exc:
        if "No generation chunks were returned" in str(exc):
            raise EmptyLLMResponseError("LLM 未返回任何内容") from exc
        raise
    except Exception:
        logger.exception("回答流式输出失败")
        raise

    reply = "".join(full_reply)
    if reply:
        logger.info("模型输出：%s", reply)
    else:
        logger.warning("模型输出为空")
    conversation_service.save_turn(session_id, content, reply)
    asyncio.create_task(_post_process(session_id, user_id, content, reply, llm=llm))


async def _post_process(
    session_id: str, user_id: str, user_input: str, ai_reply: str, llm=None
) -> None:
    try:
        if conversation_service.message_count(session_id) >= get_settings().summary_threshold:
            await summary_service.update(
                session_id, [f"用户：{user_input}", f"亚丝娜：{ai_reply}"], llm=llm
            )
    except Exception:
        logger.exception("摘要更新失败，不影响本轮回答")
    try:
        await memory_service.extract_and_save(user_id, user_input, ai_reply, llm=llm)
    except Exception:
        logger.exception("记忆提取失败，不影响本轮回答")
