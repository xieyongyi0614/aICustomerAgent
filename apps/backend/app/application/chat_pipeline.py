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
from app.application import (
    agent_runtime,
    agent_state_assembler,
    agent_state_context,
    observability,
    world_engine,
)
from app.application.agent_runtime import llm_gateway
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
from app.services.experience.style_context import build_style_context
from app.services.intention_policy import enforce as enforce_intention
from app.chains.answer_chain import answer_max_tokens
from app.repositories import relationship_milestone_repository
from app.services.action.context import build_action_context
from app.services.behavior_engine import RelationshipBehaviorContext

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


def _idle_seconds_since(moment: datetime) -> float:
    now = datetime.now(moment.tzinfo) if moment.tzinfo is not None else datetime.now()
    return max((now - moment).total_seconds(), 0.0)


def _stabilize_mode(role_mode_result, state, session_id: str) -> mode_service.ModeDecision:
    candidate, confidence = _router_candidate(role_mode_result)
    confirmed = state.mode or "default"
    idle_seconds = 0.0
    if state.mode_entered_at is not None:
        idle_seconds = _idle_seconds_since(state.mode_entered_at)
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
        goals_for_select = list(state.goals)
        if state.layered_goals:
            goals_for_select.extend(state.layered_goals)
        return goal_service.select(
            goals_for_select,
            tension=state.relationship_state.tension,
            user_emotion=state_service.load_last_user_emotion(user_id),
            character_mood=state.character_state.mood,
            character_intensity=state.character_state.intensity,
            scene_pending=_is_pending(scene_state),
            late_night=late_night,
            development_weights=_development_weights(state),
        )
    except Exception:
        logger.exception("目标选择失败，动机层降级")
        return SelectedGoal(goal=None, reason="目标选择失败，动机层降级", suppressed=[])


def _development_weights(state: ConversationState) -> dict[str, float] | None:
    overlay = getattr(state, "development_overlay", None)
    if overlay is None or not overlay.goal_weights:
        return None
    return dict(overlay.goal_weights)


def _record_development_apply(trace, state: ConversationState, behavior_ctx) -> None:
    """DEV-003：development_apply trace——调制 key/before/after/insight 溯源。"""
    if trace is None:
        return
    overlay = getattr(state, "development_overlay", None)
    if overlay is None:
        return
    applied: dict[str, dict] = {}
    if overlay.style is not None and overlay.style.max_tokens_delta < 0:
        applied["response_style.length"] = {
            "before": get_settings().answer_max_tokens,
            "after": answer_max_tokens(state),
        }
    if overlay.style is not None and overlay.style.tone_hint:
        applied["response_style.tone"] = {"before": "", "after": overlay.style.tone_hint}
    if overlay.care_hint:
        applied["behavior.care_topics"] = {"before": "", "after": overlay.care_hint}
    if overlay.habit_candidates:
        applied["behavior.habit_candidates"] = {
            "before": [],
            "after": [habit.id for habit in behavior_ctx.habits],
        }
    if overlay.goal_weights:
        applied["goal.user_care.weight"] = {
            "before": {},
            "after": dict(overlay.goal_weights),
        }
    trace.record(
        "development_apply",
        0.0,
        "ok",
        applied=applied,
        sources=dict(overlay.sources),
    )


def _apply_inventory_grounding(reply: str, content: str, world_ctx, mode: str, trace) -> str:
    try:
        from app.services.grounding.inventory_guard import (
            check_inventory_grounding,
            extract_requested_counts,
        )

        inventory = list(world_ctx.inventory or [])
        requested = extract_requested_counts(content, inventory)
        report = check_inventory_grounding(
            reply, inventory, requested=requested, context_text=content
        )
        if not report.has_conflict:
            return reply
        conflict_kinds = sorted({c.kind for c in report.conflicts})
        if trace is not None:
            trace.record(
                "inventory_grounding",
                0.0,
                "rewritten" if mode == "rewrite" and report.corrected_text else "conflict",
                conflicts=len(report.conflicts),
                kinds=conflict_kinds,
                names=[c.name for c in report.conflicts][:8],
            )
        if mode == "rewrite" and report.corrected_text:
            return report.corrected_text
        return reply
    except Exception:
        logger.exception("库存 grounding 守卫失败，放行原始回复")
        if trace is not None:
            trace.record("inventory_grounding", 0.0, "error", error="grounding crashed")
        return reply


def _run_foreground_decision(
    run_ctx, user_id: str, validated_intention, selected_goal, now: datetime
) -> dict | None:
    """前台 Run 的统一决策管线调用（AGENT-004 §5.1：前后台同一代码路径）。

    前台候选构成 = 对话响应（P0，回复用户恒优先）+ 活跃目标栈编译候选 + 静默；
    回复候选携带本轮既有意图链产出的 L0 意图，故管线胜出者恒为 chat_response，
    行为与 v2.0.0 一致；差异只体现在「候选如何评估/为什么赢」可审计。
    目标栈为只读模式（铁律 4：长期化写入只发生在后台）。
    """
    try:
        from app.services import decision_pipeline, goal_stack as goal_stack_service

        stack = goal_stack_service.evaluate_stack(
            user_id, now, retire_overdue_enabled=False
        )
        goal = getattr(selected_goal, "goal", None)
        result = decision_pipeline.run_pipeline(
            stack=stack,
            snapshot=agent_state_context.get_snapshot(),
            chat_response=True,
            chat_response_intention=getattr(validated_intention, "intention", None),
            chat_response_goal_id=getattr(validated_intention, "goal_id", None)
            or getattr(goal, "id", None),
            run=run_ctx,
            now=now,
        )
        run_ctx.data["decision"] = {
            "winner": result.winner.source if result.winner else None,
            "intention": result.intention,
            "candidates": len(result.audit.get("candidates") or []),
        }
        if result.winner is not None and result.winner.source != "chat_response":
            logger.warning(
                "前台 Run 决策胜出者非回复候选：%s（优先级铁律应保证回复优先）",
                result.winner.source,
            )
        return result.audit
    except Exception:
        logger.exception("前台决策管线失败，不影响本轮回复")
        return None


def _build_style_context(state: ConversationState, turn: TurnAnalysis, trace):
    """V2.2.0 CHAR-007：StyleContext 构造与 trace 记录。"""
    started = time.perf_counter()
    personality_state = None
    try:
        snapshot = agent_state_context.get_snapshot()
        if snapshot is not None:
            personality_state = list(snapshot.personality)
    except Exception:
        logger.exception("人格轴快照读取失败，按基线装配风格契约")
    style_ctx = build_style_context(state, turn, personality_state)
    extra = style_ctx.model_dump(mode="json") if style_ctx is not None else {}
    trace.record(
        "style_contract",
        (time.perf_counter() - started) * 1000,
        "ok" if style_ctx is not None else "skipped",
        **extra,
    )
    return style_ctx


async def run_chat_pipeline(
    session_id: str, user_id: str, content: str, llm, trace
) -> AsyncIterator[dict]:
    """前台关键路径：整链包裹为 foreground_chat Run（台账记账）。"""
    run_ctx = agent_runtime.open_foreground_run(user_id)
    status = "done"
    try:
        started = time.perf_counter()
        trace.user_id = user_id
        snapshot = await asyncio.to_thread(
            agent_state_assembler.assemble_snapshot, user_id
        )
        agent_state_assembler.activate_run_state(snapshot, run_ctx)
        world_ctx = await asyncio.to_thread(
            world_engine.build_context, user_id, session_id, trace=trace
        )
        state = await context_builder.build(session_id, user_id, content, trace=trace)
        trace.record("context_builder", (time.perf_counter() - started) * 1000)

        scene_state = await asyncio.to_thread(scene_service.load, session_id)
        current_turn = sum(1 for m in state.messages if m.role == "human") + 1

        goal_started = time.perf_counter()
        selected_goal = await asyncio.to_thread(_select_goal, state, scene_state, user_id)
        trace.record("goal_selection", (time.perf_counter() - goal_started) * 1000)

        async def _timed(name: str, coro):
            step_started = time.perf_counter()
            try:
                result = await coro
            except Exception as exc:
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
        llm_gateway.account_turn_decisions(run_ctx)
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
        decision_audit = _run_foreground_decision(
            run_ctx, user_id, validated_intention, selected_goal, datetime.now()
        )
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
            unlocks = await asyncio.to_thread(
                relationship_milestone_repository.list_unlocks, state.user_id
            )
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
            development_overlay=getattr(state, "development_overlay", None),
        )
        _record_development_apply(trace, state, behavior_ctx)
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

        style_ctx = _build_style_context(state, turn, trace)

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
        action_ctx = await asyncio.to_thread(build_action_context, user_id, session_id)
        settings = get_settings()
        grounding_mode = (
            settings.inventory_grounding_mode
            if settings.inventory_grounding_enabled and world_ctx is not None
            else "off"
        )
        buffer_reply = grounding_mode in ("rewrite", "annotate")
        answer_llm = llm_gateway.resolve_answer_llm(run_ctx, llm)
        try:
            async for token in answer_chain.astream(
                mode_decision.effective,
                state,
                turn,
                llm=answer_llm,
                trace=trace,
                scene_ctx=scene_ctx,
                goal_ctx=goal_ctx,
                behavior_ctx=behavior_ctx,
                action_ctx=action_ctx,
                world_ctx=world_ctx,
                style_ctx=style_ctx,
            ):
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - llm_started) * 1000
                full_reply.append(token)
                if not buffer_reply:
                    yield {"kind": "token", "text": token}
        except ValueError as exc:
            if not full_reply:
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
        if buffer_reply and reply:
            reply = _apply_inventory_grounding(reply, content, world_ctx, grounding_mode, trace)

        if reply:
            logger.info("模型输出完成，字符数=%d 预览=%s", len(reply), content_preview(reply))
        else:
            logger.warning("模型输出为空")
        if buffer_reply and reply:
            yield {"kind": "token", "text": reply}
        ai_message_id = await asyncio.to_thread(
            conversation_service.save_turn,
            session_id,
            content,
            reply,
            mode_write_back=(
                mode_decision.effective if mode_decision.write_back else None
            ),
        )
        try:
            await asyncio.to_thread(
                conversation_service.reset_proactive_on_user_message, user_id
            )
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
            action_intent=action_intent,
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
            pipeline_audit=decision_audit,
        )
        yield {
            "kind": "done",
            "session_id": session_id,
            "turn_id": str(ai_message_id),
            "request_id": trace.request_id,
        }

    except Exception:
        status = "aborted"
        raise
    finally:
        agent_state_assembler.reset_run_state(run_ctx)
        if status == "done" and run_ctx.degraded:
            status = "degraded"
        agent_runtime.close_run(run_ctx, status)
