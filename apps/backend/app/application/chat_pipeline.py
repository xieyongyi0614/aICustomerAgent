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
from app.application import observability, world_engine
from app.application.post_process import background_tasks, schedule_post_process
from app.prompts.goal import GoalContext
from app.services import (
    behavior_engine,
    context_builder,
    conversation_service,
    goal_service,
    mode_service,
    scene_service,
    state_service,
    trace_collector,
)
from app.services.goal_service import SelectedGoal
from app.services.action.detector import detect_action_intent
from app.services.intention_policy import enforce as enforce_intention

logger = logging.getLogger(__name__)

active_generations: dict[str, bool] = {}


class EmptyLLMResponseError(Exception):
    pass


def _router_candidate(result) -> tuple[str, float]:
    """router 输出 → (候选 mode, 置信度)；故障时返回空候选，由稳定器 R5 兜底。"""
    if isinstance(result, BaseException):
        logger.error("路由解析失败，候选置空（生效=confirmed）", exc_info=result)
        return "", 0.0
    if not isinstance(result, RoleMode):
        logger.error("路由输出非法：%r，候选置空（生效=confirmed）", result)
        return "", 0.0
    logger.info("路由候选：mode=%s confidence=%s", result.mode, result.confidence)
    return result.mode, result.confidence


def _stabilize_mode(role_mode_result, state, session_id: str) -> mode_service.ModeDecision:
    candidate, confidence = _router_candidate(role_mode_result)
    confirmed = state.mode or "default"
    idle_seconds = 0.0
    if state.mode_entered_at is not None:
        idle_seconds = max(
            (datetime.now() - state.mode_entered_at).total_seconds(), 0.0
        )
    decision = mode_service.stabilize(
        confirmed_mode=confirmed,
        candidate=candidate,
        confidence=confidence,
        session_id=session_id,
        idle_seconds=idle_seconds,
    )
    logger.info(
        "mode 稳定：confirmed=%s candidate=%s effective=%s rule=%s",
        confirmed,
        candidate,
        decision.effective,
        decision.rule,
    )
    return decision


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
    world_ctx = world_engine.build_context(user_id, session_id, trace=trace)
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

    stabilize_started = time.perf_counter()
    mode_decision = _stabilize_mode(role_mode, state, session_id)
    trace.record(
        "mode_stabilize",
        (time.perf_counter() - stabilize_started) * 1000,
    )
    if isinstance(role_mode, RoleMode):
        effective_mode = role_mode.model_copy(update={"mode": mode_decision.effective})
    else:
        effective_mode = RoleMode(
            mode=mode_decision.effective,
            intent="casual",
            confidence=0.0,
            reason="路由失败，保持已确认模式",
        )

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

    behavior_started = time.perf_counter()
    relationship_ctx = None
    try:
        from app.repositories import relationship_milestone_repository
        from app.services.behavior_engine import RelationshipBehaviorContext

        unlocks = relationship_milestone_repository.list_unlocks(state.user_id)
        rel = state.relationship_state
        relationship_ctx = RelationshipBehaviorContext(
            stage=rel.stage,
            comfort=getattr(rel, "comfort", 0.6),
            respect=getattr(rel, "respect", 0.6),
            conflict_status=getattr(rel, "conflict_status", "none") or "none",
            unlocks=unlocks,
        )
    except Exception:
        relationship_ctx = None
    behavior_ctx = behavior_engine.resolve(
        validated_intention,
        state,
        scene_ctx,
        mode_decision.effective,
        turn,
        relationship_ctx=relationship_ctx,
    )
    trace.record(
        "behavior_engine",
        (time.perf_counter() - behavior_started) * 1000,
        "degraded" if behavior_ctx.degraded else "ok",
        strategy=behavior_ctx.strategy.strategy,
        base_strategy=behavior_ctx.strategy.base_strategy,
        budget_max=behavior_ctx.budget.max_action_desc,
        matched_habits=[h.id for h in behavior_ctx.habits],
    )
    trace.set_meta(effective_mode, turn)

    behavior_meta = {
        "strategy": behavior_ctx.strategy.strategy,
        "budget": behavior_ctx.budget.model_dump(),
        "degraded": behavior_ctx.degraded,
    }
    mode_meta = {
        "confirmed": state.mode or "default",
        "effective": mode_decision.effective,
        "switched": mode_decision.switched,
    }
    trace.behavior_meta = behavior_meta
    trace.mode_meta = mode_meta

    detect_started = time.perf_counter()
    action_intent = detect_action_intent(content, scene_state=resolved_state, world_ctx=world_ctx)
    trace.record(
        "action_detect",
        (time.perf_counter() - detect_started) * 1000,
        "skipped" if action_intent is None else "ok",
    )

    turn_meta = {
        "kind": "turn_meta",
        "role_mode": effective_mode,
        "analysis": turn,
        "scene_intent": scene_intent_result,
        "scene_state": resolved_state,
        "intention": validated_intention,
        "current_goal": current_goal,
        "behavior": behavior_meta,
        "mode": mode_meta,
    }
    if action_intent is not None:
        turn_meta["action_intent"] = action_intent.model_dump(mode="json")
    yield turn_meta

    full_reply = []
    llm_started = time.perf_counter()
    first_token_ms = None
    goal_ctx = GoalContext(selected_goal=selected_goal, intention=validated_intention)
    active_generations[user_id] = True
    try:
        async for token in answer_chain.astream(
            mode_decision.effective,
            state,
            turn,
            llm=llm,
            trace=trace,
            scene_ctx=scene_ctx,
            goal_ctx=goal_ctx,
            behavior_ctx=behavior_ctx,
            world_ctx=world_ctx,
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
    finally:
        active_generations.pop(user_id, None)

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
    ai_message_id = conversation_service.save_turn(
        session_id,
        content,
        reply,
        mode_write_back=mode_decision.effective if mode_decision.write_back else None,
    )
    try:
        conversation_service.reset_proactive_on_user_message(user_id)
    except Exception:
        logger.exception("主动行为复位失败，不影响本轮对话")
    post_process_task = schedule_post_process(
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
        behavior=behavior_ctx,
    )
    collector = trace_collector.get_trace_collector()
    collector.attach(trace, str(ai_message_id))
    observability.on_turn_finished(
        trace,
        turn_id=str(ai_message_id),
        user_id=user_id,
        session_id=session_id,
        post_process_task=post_process_task,
    )
    observability.record_turn_decisions(
        trace,
        user_id=user_id,
        session_id=session_id,
        selected_goal=selected_goal,
        intention=validated_intention,
        behavior=behavior_ctx,
    )
    yield {
        "kind": "done",
        "session_id": session_id,
        "turn_id": str(ai_message_id),
        "request_id": trace.request_id,
    }

