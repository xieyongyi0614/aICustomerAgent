"""前台关键路径与后台任务编排（自 agent_service 迁入，行为不变）。

前台：上下文构建 → 目标选择 → 四链并行检测 → 意图校验 → 场景收敛 → 流式回答 → 落库 → 触发后台。
后台：scene_update ‖ state_update ‖ goal_review ‖ summary ‖ memory_extract，互相独立容错。
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import AsyncIterator

from app.chains import (
    answer_chain,
    intention_chain,
    router_chain,
    scene_intent_chain,
    turn_analysis_chain,
)
from app.core.logutils import content_preview
from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.intention import IntentionDecision
from app.models.router import RoleMode
from app.models.scene import SceneContext, SceneIntentResult, SceneState
from app.application.post_process import background_tasks, schedule_post_process
from app.prompts.goal import GoalContext
from app.services import (
    context_builder,
    conversation_service,
    goal_service,
    scene_service,
    state_service,
    trace_collector,
)
from app.services.goal_service import SelectedGoal
from app.services.intention_policy import enforce as enforce_intention

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


def _resolve_intention(result) -> IntentionDecision | None:
    if isinstance(result, BaseException):
        logger.error("意图链失败，交由策略降级", exc_info=result)
        return None
    if not isinstance(result, IntentionDecision):
        logger.error("意图输出非法：%r，交由策略降级", result)
        return None
    logger.info(
        "意图候选：%s confidence=%s reason=%s",
        result.intention,
        result.confidence,
        result.reason,
    )
    return result


def _is_pending(scene_state: SceneState | None) -> bool:
    return (
        scene_state is not None
        and scene_state.pending_action is not None
        and scene_state.pending_action.status == "pending"
    )


def _select_goal(
    state: ConversationState, scene_state: SceneState | None, user_id: str
) -> SelectedGoal:
    try:
        settings = get_settings()
        now = datetime.now()
        late_night = (
            now.hour >= settings.goal_late_night_start
            or now.hour < settings.goal_late_night_end
        )
        return goal_service.select(
            state.goals,
            tension=state.relationship_state.tension,
            user_emotion=state_service.load_last_user_emotion(user_id),
            character_mood=state.character_state.mood,
            character_intensity=state.character_state.intensity,
            scene_pending=_is_pending(scene_state),
            late_night=late_night,
        )
    except Exception:
        logger.exception("目标选择失败，动机层降级")
        return SelectedGoal(goal=None, reason="目标选择失败，动机层降级", suppressed=[])


async def run_chat_pipeline(
    session_id: str, user_id: str, content: str, llm, trace
) -> AsyncIterator[dict]:
    started = time.perf_counter()
    state = await context_builder.build(session_id, user_id, content, trace=trace)
    trace.record("context_builder", (time.perf_counter() - started) * 1000)

    scene_state = scene_service.load(session_id)
    current_turn = sum(1 for m in state.messages if m.role == "human") + 1

    goal_started = time.perf_counter()
    selected_goal = _select_goal(state, scene_state, user_id)
    trace.record("goal_selection", (time.perf_counter() - goal_started) * 1000)

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

    role_mode, analysis, scene_intent, intention_candidate = await asyncio.gather(
        _timed("role_router", router_chain.route(content, llm=llm)),
        _timed("turn_analyzer", turn_analysis_chain.analyze(content, state, llm=llm)),
        _timed("scene_intent", scene_intent_chain.classify(content, llm=llm)),
        _timed(
            "intention",
            intention_chain.decide(content, state, selected_goal, scene_state, llm=llm),
        ),
        return_exceptions=True,
    )
    if isinstance(role_mode, RoleMode):
        if role_mode.confidence < get_settings().router_confidence_threshold:
            trace.mark_status("role_router", "degraded")
    else:
        trace.mark_status("role_router", "degraded")
    if isinstance(analysis, BaseException) or not isinstance(analysis, TurnAnalysis):
        trace.mark_status("turn_analyzer", "degraded")
    if isinstance(intention_candidate, BaseException) or not isinstance(
        intention_candidate, IntentionDecision
    ):
        trace.mark_status("intention", "degraded")

    effective_mode = _effective_role_mode(role_mode)
    turn = _resolve_analysis(analysis)
    scene_intent_result = _resolve_scene_intent(scene_intent)
    intention_candidate = _resolve_intention(intention_candidate)

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
    validated_intention = enforce_intention(
        intention_candidate,
        selected_goal,
        state,
        turn,
        datetime.now(),
        scene_pending=_is_pending(resolved_state),
    )
    if validated_intention.degraded:
        trace.mark_status("intention", "degraded")
    current_goal = (
        {
            "id": selected_goal.goal.id,
            "type": selected_goal.goal.type,
            "description": selected_goal.goal.description,
        }
        if selected_goal.goal is not None
        else None
    )
    trace.set_meta(effective_mode, turn)

    yield {
        "kind": "turn_meta",
        "role_mode": effective_mode,
        "analysis": turn,
        "scene_intent": scene_intent_result,
        "scene_state": resolved_state,
        "intention": validated_intention,
        "current_goal": current_goal,
    }

    full_reply = []
    llm_started = time.perf_counter()
    first_token_ms = None
    goal_ctx = GoalContext(selected_goal=selected_goal, intention=validated_intention)
    try:
        async for token in answer_chain.astream(
            effective_mode.mode,
            state,
            turn,
            llm=llm,
            trace=trace,
            scene_ctx=scene_ctx,
            goal_ctx=goal_ctx,
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
        logger.info("模型输出完成，字符数=%d 预览=%s", len(reply), content_preview(reply))
    else:
        logger.warning("模型输出为空")
    ai_message_id = conversation_service.save_turn(session_id, content, reply)
    schedule_post_process(
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
        selected_goal=selected_goal,
        intention=validated_intention,
    )
    collector = trace_collector.get_trace_collector()
    collector.attach(trace, str(ai_message_id))
    yield {
        "kind": "done",
        "session_id": session_id,
        "turn_id": str(ai_message_id),
        "request_id": trace.request_id,
    }

