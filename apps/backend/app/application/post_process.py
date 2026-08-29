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
    goal_service,
    memory_service,
    scene_service,
    state_service,
    summary_service,
)

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
    recent_turns = ctx.state.messages[-get_settings().memory_recent_context_messages :]
    recent_context = "\n".join(
        f"用户：{m.content}" if m.role == "human" else f"亚丝娜：{m.content}"
        for m in recent_turns
    )
    try:
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
                error="extract_and_save failed",
            )


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


STEP_HANDLERS = (
    run_scene_update,
    run_state_update,
    run_goal_review,
    run_summary,
    run_memory_extract,
    run_budget_observer,
)


_user_write_locks: dict[str, asyncio.Lock] = {}


def reset_user_write_locks() -> None:
    _user_write_locks.clear()


async def run_post_process(ctx: PostProcessContext) -> None:
    lock = _user_write_locks.setdefault(ctx.user_id, asyncio.Lock())
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
    )
    task = asyncio.create_task(run_post_process(ctx))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
