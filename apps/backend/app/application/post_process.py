"""后台任务编排：步骤注册表 + 调度。

每个步骤独立容错（失败仅 trace/log，不影响其余步骤与用户对话）。
新增后台能力（V6+）只需实现 run_* 步骤并加入 STEP_HANDLERS。
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.services import (
    behavior_engine,
    conversation_service,
    evaluation_engine,
    goal_service,
    memory_service,
    scene_service,
    state_service,
    summary_service,
)
from app.application import world_engine

logger = logging.getLogger(__name__)

background_tasks: set = set()


@dataclass
class PostProcessContext:
    session_id: str
    user_id: str
    user_input: str
    ai_reply: str
    state: ConversationState
    analysis: TurnAnalysis
    scene_state: object | None = None
    scene_intent: object | None = None
    current_turn: int = 0
    llm: object | None = None
    trace: object | None = None
    selected_goal: object | None = None
    intention: object | None = None
    behavior: object | None = None
    action_intent: object | None = None


async def run_scene_update(ctx: PostProcessContext) -> None:
    if ctx.scene_state is None or ctx.scene_intent is None:
        return
    try:
        await scene_service.update_and_persist(
            ctx.session_id,
            ctx.scene_state,
            ctx.scene_intent.intent,
            ctx.user_input,
            ctx.ai_reply,
            ctx.current_turn,
            llm=ctx.llm,
            trace=ctx.trace,
        )
    except Exception:
        logger.exception("场景更新失败，保持上一轮状态")
        if ctx.trace is not None:
            ctx.trace.record("scene_update", 0.0, "error", error="scene update failed")


async def run_state_update(ctx: PostProcessContext) -> None:
    try:
        await state_service.apply_and_save(
            ctx.user_id,
            ctx.session_id,
            ctx.state,
            ctx.analysis,
            ctx.user_input,
            ctx.ai_reply,
            llm=ctx.llm,
            trace=ctx.trace,
        )
    except Exception:
        logger.exception("状态更新失败，不影响本轮回答")
        if ctx.trace is not None:
            ctx.trace.record("state_update", 0.0, "error", error="apply_and_save failed")


async def run_goal_review(ctx: PostProcessContext) -> None:
    started = time.perf_counter()
    try:
        character, relationship = state_service.load_states(ctx.user_id)
        scene = scene_service.load(ctx.session_id)
        executed = ctx.intention.intention if ctx.intention is not None else None
        changes = goal_service.review(
            ctx.user_id,
            ctx.session_id,
            ctx.analysis,
            executed,
            ctx.current_turn,
            character=character,
            relationship=relationship,
            scene=scene,
        )
        if ctx.trace is not None:
            ctx.trace.record(
                "goal_review", (time.perf_counter() - started) * 1000
            )
            if not changes.is_empty():
                logger.info(
                    "目标变更：created=%d completed=%d expired=%d cancelled=%d",
                    len(changes.created),
                    len(changes.completed),
                    len(changes.expired),
                    len(changes.cancelled),
                )
    except Exception:
        logger.exception("目标评审失败，目标保持原状，下一轮重评")
        if ctx.trace is not None:
            ctx.trace.record("goal_review", 0.0, "error", error="goal review failed")


async def run_summary(ctx: PostProcessContext) -> None:
    try:
        if conversation_service.message_count(ctx.session_id) >= get_settings().summary_threshold:
            await summary_service.update(
                ctx.session_id,
                [f"用户：{ctx.user_input}", f"亚丝娜：{ctx.ai_reply}"],
                llm=ctx.llm,
            )
    except Exception:
        logger.exception("摘要更新失败，不影响本轮回答")


async def run_memory_extract(ctx: PostProcessContext) -> None:
    started = time.perf_counter()
    try:
        if get_settings().v2_memory_enabled:
            await _run_memory_ingest_v2(ctx)
            await _run_memory_evaluate_v2(ctx)
        else:
            recent_turns = ctx.state.messages[-get_settings().memory_recent_context_messages :]
            recent_context = "\n".join(
                f"用户：{m.content}" if m.role == "human" else f"亚丝娜：{m.content}"
                for m in recent_turns
            )
            await memory_service.extract_and_save(
                ctx.user_id,
                ctx.user_input,
                ctx.ai_reply,
                llm=ctx.llm,
                trace=ctx.trace,
                recent_context=recent_context,
            )
        if ctx.trace is not None:
            ctx.trace.record(
                "memory_extractor", (time.perf_counter() - started) * 1000
            )
    except Exception:
        logger.exception("记忆提取失败，不影响本轮回答")
        if ctx.trace is not None:
            ctx.trace.record(
                "memory_extractor",
                (time.perf_counter() - started) * 1000,
                "error",
                error="memory ingest failed",
            )


async def _run_memory_ingest_v2(ctx: PostProcessContext) -> None:
    """v2 摄取通道：显式命令优先，未命中再走四源收敛到 memory_candidates。

    ActionRecord/完结 WorldEvent/RelationshipEvent 在本轮后续步骤（world/action）才产生，
    故来源候选由幂等键跨轮收敛——重复补扫不会重复产出。
    """
    from app.services.memory2 import commands as memory_commands

    outcome = await memory_commands.handle(ctx.user_id, ctx.user_input, trace=ctx.trace)
    if outcome != memory_commands.OUTCOME_MISS:
        return
    from app.chains.extractor_chain import extract_candidates
    from app.services.memory2 import ingest as memory_ingest
    from app.services.memory2 import sources as memory_sources
    from app.models.memory import MemoryExtraction

    recent_turns = ctx.state.messages[-get_settings().memory_recent_context_messages :]
    recent_context = "\n".join(
        f"用户：{m.content}" if m.role == "human" else f"亚丝娜：{m.content}"
        for m in recent_turns
    )
    extraction = await extract_candidates(
        ctx.user_input,
        ctx.ai_reply,
        recent_context=recent_context,
        llm=ctx.llm,
    )
    if not isinstance(extraction, MemoryExtraction):
        extraction = MemoryExtraction.model_validate(extraction)
    source_id_base = f"conv:{ctx.user_id}:{ctx.session_id}"
    memory_ingest.ingest_from_conversation(
        ctx.user_id,
        extraction,
        source_id_base=source_id_base,
        trace=ctx.trace,
    )
    for record in memory_sources.fetch_action_records(ctx.user_id):
        try:
            memory_ingest.ingest_from_action_record(record, trace=ctx.trace)
        except Exception:
            logger.exception("ActionRecord 摄取失败（幂等安全）：%s", record.id)
    for event in memory_sources.fetch_completed_world_events(ctx.user_id):
        try:
            memory_ingest.ingest_from_world_event(event, ctx.user_id, trace=ctx.trace)
        except Exception:
            logger.exception("WorldEvent 摄取失败（幂等安全）：%s", event.id)
    for event in memory_sources.fetch_relationship_events(ctx.user_id):
        try:
            memory_ingest.ingest_from_relationship_event(event, trace=ctx.trace)
        except Exception:
            logger.exception("RelationshipEvent 摄取失败（幂等安全）：%s", event.id)


async def _run_memory_evaluate_v2(ctx: PostProcessContext) -> None:
    """v2 评估通道：pending 候选规则分三段判定，灰区才走 lite LLM 兜底。

    尾部接线 REF-003：flush 强化缓冲并把落库 id 喂给反思事件计数；
    接线 REF-005：对本轮 approve 且 source_ref.relation=negate 的转正记忆触发
    Insight 失效匹配（MEM-005/Memory 侧 contradicts 并存语义零修改）。
    """
    from app.services.memory2 import evaluator as memory_evaluator

    decisions = await memory_evaluator.evaluate_pending(ctx.user_id, trace=ctx.trace)

    if not get_settings().v2_reflection_enabled:
        return
    try:
        from app.services.memory2 import lifecycle as memory_lifecycle
        from app.services.reflection import triggers as reflection_triggers

        flushed_ids = memory_lifecycle.flush_reinforce_buffer(trace=ctx.trace)
        if flushed_ids:
            reflection_triggers.observe_reinforce(ctx.user_id, flushed_ids, trace=ctx.trace)
    except Exception:
        logger.exception("反思事件接线失败，不影响记忆评估")
    try:
        _observe_negations(ctx, decisions)
    except Exception:
        logger.exception("反思失效通道接线失败，不影响记忆评估")


def _observe_negations(ctx: PostProcessContext, decisions) -> None:
    from app.repositories import memory_repository
    from app.services.reflection.lifecycle import observe_negation

    approved_ids = [
        decision.memory_id
        for decision in decisions
        if decision.action == "approve" and decision.memory_id
    ]
    source_refs = memory_repository.get_source_refs(approved_ids)
    for memory_id, source_ref in source_refs.items():
        if source_ref.get("relation") != "negate":
            continue
        memory = memory_repository.get_memory(memory_id)
        if memory is None:
            continue
        observe_negation(ctx.user_id, memory_id, memory.content, trace=ctx.trace)


async def run_budget_observer(ctx: PostProcessContext) -> None:
    if ctx.behavior is None:
        return
    started = time.perf_counter()
    try:
        observation = behavior_engine.observe_budget(ctx.ai_reply, ctx.behavior.budget)
        if ctx.trace is not None:
            ctx.trace.record(
                "budget_observer",
                (time.perf_counter() - started) * 1000,
                "violation" if observation["violated"] else "ok",
                **observation,
            )
        if observation["violated"]:
            logger.warning(
                "动作预算违规：actions=%d max=%d contact=%s allowed=%s",
                observation["action_count"],
                observation["budget_max"],
                observation["contact_level"],
                observation["budget_contact"],
            )
    except Exception:
        logger.exception("预算观测失败，跳过")
        if ctx.trace is not None:
            ctx.trace.record(
                "budget_observer", 0.0, "error", error="observe_budget failed"
            )


async def run_evaluation(ctx: PostProcessContext) -> None:
    """V7.5 评估第 7 步：规则阶段锁内执行，judge 采样命中时引擎派发锁外任务。"""
    try:
        evaluation_engine.run_turn_evaluation(ctx)
    except Exception:
        logger.exception("评估步骤异常（双保险，不应触达）")
        if ctx.trace is not None:
            ctx.trace.record("evaluation", 0.0, "error", error="evaluation crashed")


async def run_world_update(ctx: PostProcessContext) -> None:
    """V8 第 8 步：解释用户消息 → 世界状态迁移 + 到期处理（world-engine 侧容错）。"""
    try:
        world_engine.run_turn_update(ctx.user_id, ctx.user_input, trace=ctx.trace)
    except Exception:
        logger.exception("世界更新步骤异常（双保险，不应触达）")


async def run_action_planning(ctx: PostProcessContext) -> None:
    """V9 第 9 步：行动意图检出 → 六闸门 → 计划 → 执行 → 四通道整合。"""
    if not get_settings().action_enabled:
        return
    from app.models.action import ActionIntent

    action_intent = ctx.action_intent
    if action_intent is None:
        return
    if isinstance(action_intent, dict):
        try:
            action_intent = ActionIntent.model_validate(action_intent)
        except Exception:
            logger.exception("行动意图反序列化失败，跳过第 9 步")
            return
    started = time.perf_counter()
    try:
        from app.application.action_engine import run_action_planning as _run

        selected_goal = ctx.selected_goal
        goal_id = None
        if selected_goal is not None:
            goal = getattr(selected_goal, "goal", None)
            if goal is not None:
                goal_id = getattr(goal, "id", None)
        await _run(
            ctx.user_id,
            action_intent,
            session_id=ctx.session_id,
            goal_id=goal_id,
        )
        if ctx.trace is not None:
            ctx.trace.record(
                "action_planning",
                (time.perf_counter() - started) * 1000,
            )
    except Exception:
        logger.exception("行动规划步骤异常（双保险，不应触达）")
        if ctx.trace is not None:
            ctx.trace.record(
                "action_planning", 0.0, "error", error="action planning crashed"
            )


STEP_HANDLERS = (
    run_scene_update,
    run_state_update,
    run_goal_review,
    run_summary,
    run_memory_extract,
    run_budget_observer,
    run_evaluation,
    run_world_update,
    run_action_planning,
)


_user_write_locks: dict[str, asyncio.Lock] = {}


def get_user_write_lock(user_id: str) -> asyncio.Lock:
    """per-user 写锁公共入口（REF-010）；V7 Executor 复用同一把锁。"""
    return _user_write_locks.setdefault(user_id, asyncio.Lock())


def reset_user_write_locks() -> None:
    _user_write_locks.clear()


async def run_post_process(ctx: PostProcessContext) -> None:
    lock = get_user_write_lock(ctx.user_id)
    async with lock:
        for handler in STEP_HANDLERS:
            await handler(ctx)


def schedule_post_process(
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
    selected_goal=None,
    intention=None,
    behavior=None,
    action_intent=None,
) -> None:
    ctx = PostProcessContext(
        session_id=session_id,
        user_id=user_id,
        user_input=user_input,
        ai_reply=ai_reply,
        state=state,
        analysis=analysis,
        scene_state=scene_state,
        scene_intent=scene_intent,
        current_turn=current_turn,
        llm=llm,
        trace=trace,
        selected_goal=selected_goal,
        intention=intention,
        behavior=behavior,
        action_intent=action_intent,
    )
    task = asyncio.create_task(run_post_process(ctx))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task
