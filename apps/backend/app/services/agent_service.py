import asyncio
import logging
from typing import AsyncIterator

from app.chains import answer_chain, router_chain, turn_analysis_chain
from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.router import RoleMode
from app.services import (
    context_builder,
    conversation_service,
    memory_service,
    state_service,
    summary_service,
)

logger = logging.getLogger(__name__)


class EmptyLLMResponseError(Exception):
    pass


def _effective_role_mode(result) -> RoleMode:
    if isinstance(result, BaseException):
        logger.error("路由解析失败，降级 default", exc_info=result)
        return RoleMode(
            mode="default",
            intent="casual",
            confidence=0.0,
            reason="路由失败，降级 default",
        )
    if not isinstance(result, RoleMode):
        logger.error("路由输出非法：%r，降级 default", result)
        return RoleMode(
            mode="default",
            intent="casual",
            confidence=0.0,
            reason="路由输出非法，降级 default",
        )
    logger.info("路由输出：mode=%s confidence=%s", result.mode, result.confidence)
    if result.confidence < get_settings().router_confidence_threshold:
        logger.warning("路由低置信度(%s)，降级 default：%s", result.confidence, result.reason)
        return RoleMode(
            mode="default",
            intent=result.intent,
            confidence=result.confidence,
            reason=f"低置信度降级：{result.reason}",
        )
    return result


def _resolve_mode(result) -> str:
    return _effective_role_mode(result).mode


def _resolve_analysis(result) -> TurnAnalysis:
    if isinstance(result, BaseException):
        logger.error("轮次分析失败，使用默认分析", exc_info=result)
        return TurnAnalysis()
    if not isinstance(result, TurnAnalysis):
        logger.error("轮次分析输出非法：%r，使用默认分析", result)
        return TurnAnalysis()
    logger.info(
        "轮次分析：emotion=%s event=%s behavior=%s",
        result.user_emotion.emotion,
        result.user_emotion.event,
        result.behavior.behavior,
    )
    return result


async def stream_chat(
    session_id: str, user_id: str, content: str, llm=None
) -> AsyncIterator[dict]:
    state = await context_builder.build(session_id, user_id, content)
    role_mode, analysis = await asyncio.gather(
        router_chain.route(content, llm=llm),
        turn_analysis_chain.analyze(content, state, llm=llm),
        return_exceptions=True,
    )
    effective_mode = _effective_role_mode(role_mode)
    turn = _resolve_analysis(analysis)

    yield {"kind": "turn_meta", "role_mode": effective_mode, "analysis": turn}

    full_reply = []
    try:
        async for token in answer_chain.astream(effective_mode.mode, state, turn, llm=llm):
            full_reply.append(token)
            yield {"kind": "token", "text": token}
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
    ai_message_id = conversation_service.save_turn(session_id, content, reply)
    asyncio.create_task(
        _post_process(session_id, user_id, content, reply, state, turn, llm=llm)
    )
    yield {
        "kind": "done",
        "session_id": session_id,
        "turn_id": str(ai_message_id),
    }


async def _post_process(
    session_id: str,
    user_id: str,
    user_input: str,
    ai_reply: str,
    state: ConversationState,
    analysis: TurnAnalysis,
    llm=None,
) -> None:
    try:
        await state_service.apply_and_save(
            user_id, session_id, state, analysis, user_input, ai_reply, llm=llm
        )
    except Exception:
        logger.exception("状态更新失败，不影响本轮回答")
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
