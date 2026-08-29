import asyncio
import logging
import time
from typing import AsyncIterator

from app.chains import (
    answer_chain,
    router_chain,
    scene_intent_chain,
    turn_analysis_chain,
)
from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.router import RoleMode
from app.models.scene import SceneContext, SceneIntentResult
from app.services import (
    context_builder,
    conversation_service,
    memory_service,
    scene_service,
    state_service,
    summary_service,
    trace_collector,
)

logger = logging.getLogger(__name__)

_background_tasks: set = set()


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


def _resolve_scene_intent(result) -> SceneIntentResult:
    if isinstance(result, BaseException) or not isinstance(result, SceneIntentResult):
        logger.error("场景意图识别失败，降级 chat")
        return SceneIntentResult(
            intent="chat", confidence=0.0, reason="scene_intent degraded"
        )
    return result


async def stream_chat(
    session_id: str, user_id: str, content: str, llm=None
) -> AsyncIterator[dict]:
    trace = trace_collector.get_trace_collector().begin_trace()
    try:
        async for event in _stream_chat_inner(
            session_id, user_id, content, llm, trace
        ):
            yield event
    except BaseException as exc:
        trace.record(
            "llm",
            0.0,
            "error",
            error=exc.__class__.__name__,
        )
        raise


async def _stream_chat_inner(
    session_id: str, user_id: str, content: str, llm, trace
) -> AsyncIterator[dict]:
    started = time.perf_counter()
    state = await context_builder.build(session_id, user_id, content, trace=trace)
    trace.record("context_builder", (time.perf_counter() - started) * 1000)

    scene_state = scene_service.load(session_id)
    current_turn = sum(1 for m in state.messages if m.role == "human") + 1

    async def _timed(name: str, coro):
        step_started = time.perf_counter()
        try:
            result = await coro
        except BaseException as exc:
            trace.record(
                name,
                (time.perf_counter() - step_started) * 1000,
                "error",
                error=exc.__class__.__name__,
            )
            raise
        trace.record(name, (time.perf_counter() - step_started) * 1000)
        return result

    role_mode, analysis, scene_intent = await asyncio.gather(
        _timed("role_router", router_chain.route(content, llm=llm)),
        _timed("turn_analyzer", turn_analysis_chain.analyze(content, state, llm=llm)),
        _timed("scene_intent", scene_intent_chain.classify(content, llm=llm)),
        return_exceptions=True,
    )
    if isinstance(role_mode, RoleMode):
        if role_mode.confidence < get_settings().router_confidence_threshold:
            trace.mark_status("role_router", "degraded")
    else:
        trace.mark_status("role_router", "degraded")
    if isinstance(analysis, BaseException) or not isinstance(analysis, TurnAnalysis):
        trace.mark_status("turn_analyzer", "degraded")

    effective_mode = _effective_role_mode(role_mode)
    turn = _resolve_analysis(analysis)
    scene_intent_result = _resolve_scene_intent(scene_intent)

    resolver_started = time.perf_counter()
    resolved_state, directive = scene_service.resolve(
        scene_intent_result.intent, scene_state, current_turn
    )
    trace.record("scene_resolver", (time.perf_counter() - resolver_started) * 1000)

    scene_ctx = SceneContext(
        state=resolved_state,
        intent=scene_intent_result.intent,
        directive=directive,
    )
    trace.set_meta(effective_mode, turn)

    yield {
        "kind": "turn_meta",
        "role_mode": effective_mode,
        "analysis": turn,
        "scene_intent": scene_intent_result,
        "scene_state": resolved_state,
    }

    full_reply = []
    llm_started = time.perf_counter()
    first_token_ms = None
    try:
        async for token in answer_chain.astream(
            effective_mode.mode, state, turn, llm=llm, trace=trace, scene_ctx=scene_ctx
        ):
            if first_token_ms is None:
                first_token_ms = (time.perf_counter() - llm_started) * 1000
            full_reply.append(token)
            yield {"kind": "token", "text": token}
    except ValueError as exc:
        if "No generation chunks were returned" in str(exc):
            trace.record(
                "llm",
                (time.perf_counter() - llm_started) * 1000,
                "error",
                first_token_ms=first_token_ms,
                error="empty response",
            )
            raise EmptyLLMResponseError("LLM 未返回任何内容") from exc
        raise
    except Exception as exc:
        trace.record(
            "llm",
            (time.perf_counter() - llm_started) * 1000,
            "error",
            first_token_ms=first_token_ms,
            error=exc.__class__.__name__,
        )
        logger.exception("回答流式输出失败")
        raise

    trace.record(
        "llm",
        (time.perf_counter() - llm_started) * 1000,
        "ok",
        first_token_ms=first_token_ms,
    )

    reply = "".join(full_reply)
    if reply:
        logger.info("模型输出：%s", reply)
    else:
        logger.warning("模型输出为空")
    ai_message_id = conversation_service.save_turn(session_id, content, reply)
    task = asyncio.create_task(
        _post_process(
            session_id,
            user_id,
            content,
            reply,
            state,
            turn,
            scene_state=resolved_state,
            scene_intent=scene_intent_result,
            current_turn=current_turn,
            llm=llm,
            trace=trace,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    collector = trace_collector.get_trace_collector()
    collector.attach(trace, str(ai_message_id))
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
    scene_state=None,
    scene_intent=None,
    current_turn: int = 0,
    llm=None,
    trace=None,
) -> None:
    if scene_state is not None and scene_intent is not None:
        try:
            await scene_service.update_and_persist(
                session_id,
                scene_state,
                scene_intent.intent,
                user_input,
                ai_reply,
                current_turn,
                llm=llm,
                trace=trace,
            )
        except Exception:
            logger.exception("场景更新失败，保持上一轮状态")
            if trace is not None:
                trace.record(
                    "scene_update", 0.0, "error", error="scene update failed"
                )
    try:
        await state_service.apply_and_save(
            user_id, session_id, state, analysis, user_input, ai_reply, llm=llm, trace=trace
        )
    except Exception:
        logger.exception("状态更新失败，不影响本轮回答")
        if trace is not None:
            trace.record("state_update", 0.0, "error", error="apply_and_save failed")
    try:
        if conversation_service.message_count(session_id) >= get_settings().summary_threshold:
            await summary_service.update(
                session_id, [f"用户：{user_input}", f"亚丝娜：{ai_reply}"], llm=llm
            )
    except Exception:
        logger.exception("摘要更新失败，不影响本轮回答")
    started = time.perf_counter()
    recent_turns = state.messages[-4:]
    recent_context = "\n".join(
        f"用户：{m.content}" if m.role == "human" else f"亚丝娜：{m.content}"
        for m in recent_turns
    )
    try:
        await memory_service.extract_and_save(
            user_id,
            user_input,
            ai_reply,
            llm=llm,
            trace=trace,
            recent_context=recent_context,
        )
        if trace is not None:
            trace.record("memory_extractor", (time.perf_counter() - started) * 1000)
    except Exception:
        logger.exception("记忆提取失败，不影响本轮回答")
        if trace is not None:
            trace.record(
                "memory_extractor",
                (time.perf_counter() - started) * 1000,
                "error",
                error="extract_and_save failed",
            )
