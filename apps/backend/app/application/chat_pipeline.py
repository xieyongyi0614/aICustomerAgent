"""前台关键路径与后台任务编排（自 agent_service 迁入，行为不变）。

前台：上下文构建 → 目标选择 → 四链并行检测 → 意图校验 → 场景收敛 → 流式回答 → 落库 → 触发后台。
后台：scene_update ‖ state_update ‖ goal_review ‖ summary ‖ memory_extract，互相独立容错。

本模块只提供「段实现」与薄驱动，**不含手写段序**：
- 段**序**由 `agent_runtime/profiles.py` 的 `foreground_chat` Profile 声明；
- 段**本体**是 `run_chat_pipeline` 内的闭包（捕获 25+ `nonlocal` 中间值），
  经 `_foreground_registry` 登记为 `{段名: runner}` 后交给 `AgentLoop` 驱动；
- 生产路径固定为 `AgentLoop`（建台账 + 运行时事件）；C-2 线性旧链与
  `runtime_foreground_loop_enabled` 字段已于 2026-10-15 物理删除，
  前台回退 = git revert。
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
from app.core import timeutil
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
from app.application.agent_runtime import context as runtime_context_manager
from app.application.agent_runtime import llm_gateway
from app.application.agent_runtime import profiles as runtime_profiles
from app.application.agent_runtime import state as runtime_state_manager
from app.application.agent_runtime.contracts import RuntimeInput, SessionContext
from app.application.agent_runtime.loop import AgentLoop
from app.application.agent_runtime.models import RUN_KIND_FOREGROUND_CHAT
from app.application.post_process import background_tasks, schedule_post_process
from app.prompts.goal import GoalContext
from app.engines import behavior as behavior_engine
from app.services.conversation import context as context_builder
from app.services.conversation import service as conversation_service
from app.services.goal import service as goal_service
from app.engines import mode as mode_service
from app.services.conversation import scene as scene_service
from app.services.conversation import state as state_service
from app.services.observability import collector as trace_collector
from app.services.goal.service import SelectedGoal
from app.services.action.detector import detect_action_intent
from app.services.experience.style_context import build_style_context
from app.services.goal.intention import enforce as enforce_intention
from app.chains.answer_chain import answer_max_tokens
from app.repositories import relationship_milestone_repository
from app.services.action.context import build_action_context
from app.engines.behavior import RelationshipBehaviorContext
from app.services.memory.refs import build_memory_refs

logger = logging.getLogger(__name__)

from app.core.runtime_state import active_generations


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
    now = timeutil.now()
    return max((now - timeutil.ensure_aware(moment)).total_seconds(), 0.0)


def _stabilize_mode(role_mode_result, state, session_id: str) -> mode_service.ModeDecision:
    """模式稳定：把 router 的「候选模式」与已确认模式比对，抑制抖动后给出生效模式。

    已确认模式来自持久化 state，候选来自本轮 router 链；稳定器（R5）据候选置信度与
    距上次切换的时长（idle_seconds）决定是否切换，避免一句话就来回改角色语气。
    """
    candidate, confidence = _router_candidate(role_mode_result)
    confirmed = state.mode or "default"
    # 距上次进入当前模式已过多久：稳定器用它做「切换冷却」。
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
    """轮次分析归一：异常或非法输出一律降级为默认 `TurnAnalysis()`。"""
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
    """场景意图归一：失败 / 非法降级为 `intent=chat`（当作普通闲聊处理）。"""
    if isinstance(result, BaseException) or not isinstance(result, SceneIntentResult):
        logger.error("场景意图识别失败，降级 chat")
        return SceneIntentResult(
            intent="chat", confidence=0.0, reason="scene_intent degraded"
        )
    return result


def _resolve_intention(result) -> IntentionDecision | None:
    """意图归一：失败 / 非法返回 None，交由下游策略（enforce_intention）降级。"""
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
    """场景是否处于「待用户确认」态：存在 pending_action 且状态为 pending。"""
    return (
        scene_state is not None
        and scene_state.pending_action is not None
        and scene_state.pending_action.status == "pending"
    )


def _select_goal(
    state: ConversationState, scene_state: SceneState | None, user_id: str
) -> SelectedGoal:
    """本轮目标选择：候选目标 + 多维上下文 → 目标服务打分 → 选出本轮要推进的目标。

    输入维度：关系张力 / 用户情绪 / 角色心情与强度 / 是否有待确认场景 / 是否深夜 /
    development 覆盖权重。失败降级为「无目标」（动机层降级，不影响本轮回复）。
    """
    try:
        settings = get_settings()
        now = timeutil.local_now()
        late_night = (
            timeutil.local(now).hour >= settings.goal_late_night_start
            or timeutil.local(now).hour < settings.goal_late_night_end
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
    """development 覆盖层给出的目标权重；无覆盖时返回 None（由目标服务用基线权重）。"""
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
    """库存 grounding 守卫：检查回复是否与角色背包 / 世界物品矛盾，命中且 mode=rewrite 时纠正。

    仅在 `inventory_grounding_mode ∈ {rewrite, annotate}` 时调用（此时回复被缓冲、可整段改）；
    守卫自身异常一律放行原始回复（grounding 不得成为硬失败点）。
    """
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
        from app.engines import decision as decision_pipeline
        from app.services.goal import stack as goal_stack_service

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


# ---------------------------------------------------------------------------
# RT-015 前台循环收编：段实现 + 薄驱动
#
# 段序列**只**来自 `profiles.py` 的 `foreground_chat` Profile（本模块不含任何手写
# 阶段序列）；段本体经 `AgentLoop(..., registry=...)` 按 Run 注入，故前台段与自治段
# 可同名共存而无需改循环内核结构。流式协议（turn_meta / token / done）与 22 步业务
# 实现逐字段保留；等价性硬约束清单见 docs/version/v3.0.0/entry-convergence.md。
# ---------------------------------------------------------------------------

def _foreground_registry(runners: dict) -> dict:
    """校验前台段实现完整性；段**序**本身只由 Profile 声明（AC2）。"""
    spec = runtime_profiles.get_profile(RUN_KIND_FOREGROUND_CHAT)
    missing = [name for name in spec.stages if name not in runners]
    if missing:
        raise ValueError(f"前台段实现缺失：{missing}")
    return dict(runners)


async def run_chat_pipeline(
    session_id: str,
    user_id: str,
    content: str,
    llm=None,
    trace=None,
    *,
    runtime_input: RuntimeInput | None = None,
    session_context: SessionContext | None = None,
) -> AsyncIterator[dict]:
    """前台关键路径（RT-015 收编）：流式协议不变，段序列来自 foreground_chat Profile。

    生产路径固定经 `AgentLoop`（建台账 + 运行时事件）；C-2 线性旧链与
    `runtime_foreground_loop_enabled` 字段已于 2026-10-15 物理删除，
    无回退开关（回退 = git revert）。
    """
    events: asyncio.Queue = asyncio.Queue()
    run_ctx = agent_runtime.open_foreground_run(user_id, session_id=session_id)
    runtime_state_manager.activate(run_ctx, user_id)
    runtime_context_value = None
    # 护栏：前台九段闭包与生产调用点均未消费冻结上下文（stream_chat 不传
    # session_context，业务链仍自建 state/world_ctx），开启即双倍构建纯开销；
    # 接线点在 _context_assembly 复用 context.current(run)。
    if (
        get_settings().runtime_context_freeze_enabled
        and session_context is not None
    ):
        runtime_context_value = await runtime_context_manager.assemble(
            session_context,
            runtime_input,
            run=run_ctx,
            trace=trace,
        )
    spec = runtime_profiles.get_profile(RUN_KIND_FOREGROUND_CHAT)
    stage_error: BaseException | None = None

    # 段间中间值（闭包共享；只活在本次 Run，不落业务表）
    snapshot = None
    world_ctx = None
    state = None
    scene_state = None
    current_turn = 0
    selected_goal = None
    role_mode = None
    analysis = None
    scene_intent = None
    intention_candidate = None
    mode_decision = None
    effective_mode = None
    turn = None
    scene_intent_result = None
    resolved_state = None
    directive = None
    scene_ctx = None
    validated_intention = None
    decision_audit = None
    current_goal = None
    relationship_ctx = None
    behavior_ctx = None
    style_ctx = None
    behavior_meta: dict = {}
    mode_meta: dict = {}
    action_intent = None
    full_reply: list = []
    first_token_ms = None
    reply = ""
    ai_message_id = None

    async def _perception(_ctx):
        """Observe 段锚点：入站已由 RT-013 网关归一，本段不引入额外业务。"""
        if stage_error is not None:
            return {"status": "skipped"}
        return {"status": "ok"}

    async def _context_assembly(_ctx):
        """第 2 段：装配上下文——AgentState 快照 / 世界上下文 / 会话状态 / 场景，并选出本轮目标。"""
        nonlocal snapshot, world_ctx, state, scene_state, current_turn, selected_goal
        nonlocal stage_error
        if stage_error is not None:
            return {"status": "skipped"}
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
            selected_goal = await asyncio.to_thread(
                _select_goal, state, scene_state, user_id
            )
            trace.record("goal_selection", (time.perf_counter() - goal_started) * 1000)
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    async def _turn_decisions(_ctx):
        """第 3 段：四链并行（角色路由 / 轮次分析 / 场景意图 / 意图决策），单链失败即降级。"""
        nonlocal role_mode, analysis, scene_intent, intention_candidate
        nonlocal turn, scene_intent_result, stage_error
        if stage_error is not None:
            return {"status": "skipped"}
        try:

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

            # return_exceptions=True：四链互不拖累，失败项以异常对象返回，下面逐项归一。
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
            turn = _resolve_analysis(analysis)
            scene_intent_result = _resolve_scene_intent(scene_intent)
            intention_candidate = _resolve_intention(intention_candidate)
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    async def _mode_stabilize(_ctx):
        """第 4 段：模式稳定——产出本轮生效的角色模式 `effective_mode`。"""
        nonlocal mode_decision, effective_mode, stage_error
        if stage_error is not None:
            return {"status": "skipped"}
        try:
            stabilize_started = time.perf_counter()
            mode_decision = _stabilize_mode(role_mode, state, session_id)
            trace.record(
                "mode_stabilize", (time.perf_counter() - stabilize_started) * 1000
            )
            if isinstance(role_mode, RoleMode):
                effective_mode = role_mode.model_copy(
                    update={"mode": mode_decision.effective}
                )
            else:
                effective_mode = RoleMode(
                    mode=mode_decision.effective,
                    intent="casual",
                    confidence=0.0,
                    reason="路由失败，保持已确认模式",
                )
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    async def _scene_resolve(_ctx):
        """第 5 段：场景收敛 + 意图校验（enforce_intention）+ 前台决策管线（目标栈只读）。"""
        nonlocal resolved_state, directive, scene_ctx
        nonlocal validated_intention, decision_audit, current_goal, stage_error
        if stage_error is not None:
            return {"status": "skipped"}
        try:
            resolver_started = time.perf_counter()
            resolved_state, directive = scene_service.resolve(
                scene_intent_result.intent, scene_state, current_turn
            )
            trace.record(
                "scene_resolver", (time.perf_counter() - resolver_started) * 1000
            )
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
                timeutil.now(),
                scene_pending=_is_pending(resolved_state),
            )
            if validated_intention.degraded:
                trace.mark_status("intention", "degraded")
            decision_audit = _run_foreground_decision(
                run_ctx, user_id, validated_intention, selected_goal, timeutil.now()
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
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    async def _behavior_resolve(_ctx):
        """第 6 段：关系上下文 + 行为引擎 + 风格契约（决定「怎么回应」）。"""
        nonlocal relationship_ctx, behavior_ctx, style_ctx, stage_error
        if stage_error is not None:
            return {"status": "skipped"}
        try:
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
            behavior_meta.update(
                {
                    "strategy": behavior_ctx.strategy.strategy,
                    "budget": behavior_ctx.budget.model_dump(),
                    "degraded": behavior_ctx.degraded,
                }
            )
            mode_meta.update(
                {
                    "confirmed": state.mode or "default",
                    "effective": mode_decision.effective,
                    "switched": mode_decision.switched,
                }
            )
            trace.behavior_meta = behavior_meta
            trace.mode_meta = mode_meta
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    async def _action_planning(_ctx):
        """第 7 段：检出行动意图，并组装 / 发出首帧 `turn_meta`。"""
        nonlocal action_intent, stage_error
        if stage_error is not None:
            return {"status": "skipped"}
        try:
            detect_started = time.perf_counter()
            action_intent = detect_action_intent(
                content, scene_state=resolved_state, world_ctx=world_ctx
            )
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
            memory_refs = build_memory_refs(
                state.memories if state else None,
                state.memory_rank if state else None,
            )
            if memory_refs:
                turn_meta["memory_refs"] = memory_refs
            await events.put(turn_meta)
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    async def _reply_generation(_ctx):
        """第 8 段（唯一关键段）：流式生成回答，逐 token 推事件；grounding 重写时补发替换帧。"""
        nonlocal full_reply, first_token_ms, reply, stage_error
        if stage_error is not None:
            return {"status": "skipped"}
        try:
            llm_started = time.perf_counter()
            goal_ctx = GoalContext(
                selected_goal=selected_goal, intention=validated_intention
            )
            active_generations[user_id] = True
            action_ctx = await asyncio.to_thread(
                build_action_context, user_id, session_id
            )
            settings = get_settings()
            # grounding 重写需「看到完整回复」才能纠错，故 rewrite/annotate 模式下缓冲整段回复。
            grounding_mode = (
                settings.inventory_grounding_mode if world_ctx is not None else "off"
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
                    await events.put({"kind": "token", "text": token})
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
                reply = _apply_inventory_grounding(
                    reply, content, world_ctx, grounding_mode, trace
                )

            if reply:
                logger.info(
                    "模型输出完成，字符数=%d 预览=%s", len(reply), content_preview(reply)
                )
            else:
                logger.warning("模型输出为空")
            # wire 契约：回复恒逐 token 流式；grounding 重写有变更时补发整段替换，
            # 客户端收到后以替换文本为最终回复。
            if buffer_reply and reply and reply != "".join(full_reply):
                await events.put({"kind": "reply_replace", "text": reply})
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    async def _record_handoff(_ctx):
        """第 9 段：落库本轮、复位主动行为、调度后台任务、发出 `done` 结束帧。"""
        nonlocal ai_message_id, stage_error
        if stage_error is not None:
            return {"status": "skipped"}
        try:
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
            await events.put(
                {
                    "kind": "done",
                    "session_id": session_id,
                    "turn_id": str(ai_message_id),
                    "request_id": trace.request_id,
                }
            )
        except BaseException as exc:
            stage_error = exc
            raise
        return {"status": "ok"}

    runners = _foreground_registry(
        {
            "perception": _perception,
            "context_assembly": _context_assembly,
            "turn_decisions": _turn_decisions,
            "mode_stabilize": _mode_stabilize,
            "scene_resolve": _scene_resolve,
            "behavior_resolve": _behavior_resolve,
            "action_planning": _action_planning,
            "reply_generation": _reply_generation,
            "record_handoff": _record_handoff,
        }
    )
    loop = AgentLoop(
        spec,
        user_id=user_id,
        run=run_ctx,
        llm=llm,
        trace=trace,
        registry=runners,
    )
    task = asyncio.ensure_future(
        loop.run(runtime_input, session_context, runtime_context=runtime_context_value)
    )
    try:
        # 事件桥：并发等待「队列出事件」与「驱动 task 结束」，谁先到先处理。
        while True:
            getter = asyncio.ensure_future(events.get())
            done, _pending = await asyncio.wait(
                {getter, task}, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                # 有事件先出：逐条 yield 给调用方（chat.py 转 NDJSON）。
                item = getter.result()
                yield item
                continue
            # task 先结束：取消待取任务，排空队列剩余事件后退出循环。
            getter.cancel()
            while not events.empty():
                yield events.get_nowait()
            break
        # 段内记录的错误优先冒泡（保证关键段失败能被上层感知）。
        if stage_error is not None:
            raise stage_error
        if task.done() and not task.cancelled() and task.exception() is not None:
            raise task.exception()
    finally:
        # 调用方提前关闭流时取消驱动 task，避免留下后台孤儿运行。
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # pylint: disable=broad-except
                pass


async def stream_chat(
    session_id: str, user_id: str, content: str, llm=None, trace=None
) -> AsyncIterator[dict]:
    """前台对话入口（自 `services/agent_service` 收编，行为不变）。

    透传 `run_chat_pipeline`，并负责 trace 兜底创建与 observability trace
    context 的 set/reset。生产侧 2 处调用点（`api/v1/chat.py`、`channels/feishu/adapter.py`）
    均显式传入 trace，故兜底分支实际只服务测试；语义与旧壳逐字一致。
    """
    if trace is None:
        trace = trace_collector.get_trace_collector().begin_trace()
    observability_token = observability.current_trace.set(trace)
    try:
        async for event in run_chat_pipeline(session_id, user_id, content, llm, trace):
            yield event
    except Exception as exc:
        trace.record(
            "llm",
            0.0,
            "error",
            error=exc.__class__.__name__,
        )
        observability.on_turn_error(trace, user_id=user_id, session_id=session_id)
        raise
    finally:
        observability.current_trace.reset(observability_token)
