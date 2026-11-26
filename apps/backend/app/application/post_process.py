"""后台任务编排：步骤注册表 + 调度。

每个步骤独立容错（失败仅 trace/log，不影响其余步骤与用户对话）。
新增后台能力（V6+）只需实现 run_* 步骤并加入 STEP_HANDLERS。
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import timeutil
from app.core.settings import get_settings
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.engines import behavior as behavior_engine
from app.services.conversation import service as conversation_service
from app.services.evaluation import engine as evaluation_engine
from app.services.goal import service as goal_service
from app.services.conversation import scene as scene_service
from app.services.conversation import state as state_service
from app.services.conversation import summary as summary_service
from app.services.autonomy import trigger as trigger_evaluator
from app.application import world_engine
from app.models.action import ActionIntent
from app.models.character_action import TurnRef
from app.models.memory import MemoryExtraction
from app.repositories import memory_repository, world_repository
from app.services.memory import (
    commands as memory_commands,
    ingest as memory_ingest,
    sources as memory_sources,
    evaluator as memory_evaluator,
    lifecycle as memory_lifecycle,
)
from app.services.reflection import triggers as reflection_triggers
from app.services.reflection.lifecycle import observe_negation

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
    # 本轮登记待确认的账目金额（分）：确定性链路据此让位，保证同一笔只有一个写面
    ledger_pending_amount: int | None = None


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
        await _ingest_memory_candidates(ctx)
        await _evaluate_memory_candidates(ctx)
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


async def _ingest_memory_candidates(ctx: PostProcessContext) -> None:
    """v2 摄取通道：显式命令优先，未命中再走四源收敛到 memory_candidates。

    ActionRecord/完结 WorldEvent/RelationshipEvent 在本轮后续步骤（world/action）才产生，
    故来源候选由幂等键跨轮收敛——重复补扫不会重复产出。
    """

    outcome = await memory_commands.handle(ctx.user_id, ctx.user_input, trace=ctx.trace)
    if outcome != memory_commands.OUTCOME_MISS:
        return

    recent_turns = ctx.state.messages[-get_settings().memory_recent_context_messages :]
    recent_context = "\n".join(
        f"用户：{m.content}" if m.role == "human" else f"亚丝娜：{m.content}"
        for m in recent_turns
    )
    from app.chains.extractor_chain import extract_candidates

    extraction = await extract_candidates(
        ctx.user_input,
        ctx.ai_reply,
        recent_context=recent_context,
        llm=ctx.llm,
    )
    if not isinstance(extraction, MemoryExtraction):
        extraction = MemoryExtraction.model_validate(extraction)
    source_id_base = f"conv:{ctx.user_id}:{ctx.session_id}"
    conversation_rows = memory_ingest.ingest_from_conversation(
        ctx.user_id,
        extraction,
        source_id_base=source_id_base,
        trace=ctx.trace,
    )
    _register_followups(ctx.user_id, conversation_rows)
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
    for milestone in memory_sources.fetch_recent_relationship_milestones(ctx.user_id):
        try:
            memory_ingest.ingest_from_relationship_milestone(
                milestone, trace=ctx.trace
            )
        except Exception:
            logger.exception(
                "RelationshipMilestone 摄取失败（幂等安全）：%s", milestone.id
            )


def _register_followups(user_id: str, rows) -> None:
    """V7-010：带时间语义的事件候选 → scheduled_followup 登记。

    唯一生产者原为 v1 `extract_and_save`（随其删除断链），现承接于 v2 摄取通道
    的会话候选行；due = 最近一次 18:00（已过则顺延次日），消费端 `poll_due_followup`
    与登记表写入均为既有通道。
    """
    now = timeutil.now()
    for row in rows:
        keyword = trigger_evaluator.find_followup_event(row.content or "")
        if keyword is None:
            continue
        due = now.replace(hour=18, minute=0, second=0, microsecond=0)
        if due <= now:
            due += timedelta(days=1)
        try:
            trigger_evaluator.register_followup(user_id, due, f"{keyword}近况跟进")
            logger.info("scheduled_followup 登记：%s due=%s", keyword, due)
        except Exception:
            logger.exception("followup 登记失败，跳过")


async def _evaluate_memory_candidates(ctx: PostProcessContext) -> None:
    """v2 评估通道：pending 候选规则分三段判定，灰区才走 lite LLM 兜底。

    尾部接线 REF-003：flush 强化缓冲并把落库 id 喂给反思事件计数；
    接线 REF-005：对本轮 approve 且 source_ref.relation=negate 的转正记忆触发
    Insight 失效匹配（MEM-005/Memory 侧 contradicts 并存语义零修改）。
    """

    decisions = await memory_evaluator.evaluate_pending(
        ctx.user_id, trace=ctx.trace, llm=ctx.llm
    )

    try:
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
    """V7.5 评估第 7 步：规则阶段锁内执行，judge 采样命中时引擎派发后台任务。"""
    try:
        evaluation_engine.run_turn_evaluation(ctx)
    except Exception:
        logger.exception("评估步骤异常（双保险，不应触达）")
        if ctx.trace is not None:
            ctx.trace.record("evaluation", 0.0, "error", error="evaluation crashed")


async def run_world_update(ctx: PostProcessContext) -> None:
    """V8 第 8 步：解释用户消息 → 世界状态迁移 + 到期处理（world-engine 侧容错）。
    V2.3.0 追加：用户处境检出（确定性模式，独立子闸）。
    物品录入（2026-10-10）：步骤**内部**增强（不新增步骤、不改序列）——默认家庭库存
    种子已移除，物品只在用户**显式要求记录**时（确定性前置闸命中）走 LLM 抽取建档。"""
    try:
        world_engine.run_turn_update(ctx.user_id, ctx.user_input, trace=ctx.trace)
    except Exception:
        logger.exception("世界更新步骤异常（双保险，不应触达）")
    try:
        from app.services.world import user_situation

        user_situation.detect_from_message(
            ctx.user_id,
            ctx.user_input,
            evidence={"session_id": ctx.session_id, "turn": ctx.current_turn},
        )
    except Exception:
        logger.exception("用户处境检出异常")
    await _run_object_intake(ctx)


async def _run_object_intake(ctx: PostProcessContext) -> None:
    """用户显式要求记录物品 → LLM 抽取 → 建档。

    幂等：同名物品已存在则跳过（避免与词表链路/多轮重复录入）。前置闸未命中零 LLM。
    """
    from app.chains.object_intake_chain import extract_objects, has_record_intent

    if not has_record_intent(ctx.user_input):
        return
    started = time.perf_counter()
    try:
        intake = await asyncio.to_thread(extract_objects, ctx.user_input, llm=ctx.llm)
        created: list[str] = []
        for item in intake.items:
            if world_engine.find_object_by_name(ctx.user_id, item.name) is not None:
                continue
            obj = world_engine.create_object(
                ctx.user_id,
                name=item.name,
                category=item.category,
                quantity=item.quantity,
                unit=item.unit,
                consumable=item.category in ("food", "drink"),
                **{
                    key: value
                    for key, value in (
                        ("price_minor", item.price_minor),
                        ("purchased_at", item.purchased_at),
                    )
                    if value is not None
                },
            )
            if obj is not None:
                created.append(item.name)
        if ctx.trace is not None:
            ctx.trace.record(
                "object_intake",
                (time.perf_counter() - started) * 1000,
                "ok",
                extracted=len(intake.items),
                created=len(created),
            )
    except Exception:
        logger.exception("物品录入失败，不影响本轮回答")
        if ctx.trace is not None:
            ctx.trace.record("object_intake", 0.0, "error", error="object intake failed")


async def run_character_action_sync(ctx: PostProcessContext) -> None:
    """CAS 第 9 步：提取 → 校验 → 执行（ACTION-004）→ 摘要写 notes（ACTION-005 写侧）。"""
    started = time.perf_counter()
    try:
        from app.services.character_action.extractor import extract_actions
        from app.services.character_action.mutator import execute_actions
        from app.services.character_action.validator import validate_actions

        world = world_engine.ensure_world(ctx.user_id)
        if world is None:
            if ctx.trace is not None:
                ctx.trace.record("character_action_sync", 0.0, "error", error="world unavailable")
            return
        known_names: set[str] = set()
        for obj in world_repository.list_objects(world.world_id):
            known_names.add(obj.name)
            known_names.update(obj.aliases or [])
        completed = world_repository.list_events(
            world.world_id,
            statuses=["completed"],
            limit=50,
            types=["character_action"],
            order="created_at_desc",
        )
        recent_dedupe_keys = {
            event.payload.get("dedupe_key")
            for event in completed
            if event.payload.get("dedupe_key")
        }
        turn_ref = TurnRef(
            session_id=ctx.session_id,
            turn_id=f"{ctx.session_id}:turn{ctx.current_turn}",
            ordinal=0,
        )
        recent = ctx.state.messages[-get_settings().memory_recent_context_messages:]
        context_text = "\n".join(
            f"用户：{m.content}" if m.role == "human" else f"亚丝娜：{m.content}"
            for m in recent
        )
        extracted = extract_actions(
            ctx.ai_reply,
            known_object_names=known_names,
            turn_ref=turn_ref,
            context_text=context_text,
        )
        validation = validate_actions(
            extracted.candidates,
            world_id=world.world_id,
            user_id=ctx.user_id,
            recent_dedupe_keys=recent_dedupe_keys,
        )
        validated = [result.action for result in validation if result.status == "validated"]
        outcomes = execute_actions(validated, user_id=ctx.user_id, trace=ctx.trace)
        applied = [outcome for outcome in outcomes if outcome.status == "applied"]
        cas_lines = [outcome.title for outcome in applied if outcome.title]
        merged = world_engine.merge_character_action_notes(ctx.user_id, cas_lines)
        if ctx.trace is not None:
            ctx.trace.record(
                "character_action_sync",
                (time.perf_counter() - started) * 1000,
                "ok",
                extracted=len(extracted.candidates),
                rejected=len(validation) - len(validated),
                applied=len(applied),
                notes_merged=merged,
                event_ids=[outcome.world_event_id for outcome in applied if outcome.world_event_id],
            )
    except Exception:
        logger.exception("角色动作同步步骤异常（双保险，不应触达）")
        if ctx.trace is not None:
            ctx.trace.record(
                "character_action_sync", 0.0, "error", error="character action sync crashed"
            )


def _defer_to_ledger_pending(
    ctx: PostProcessContext, intent: ActionIntent
) -> bool:
    """本轮同一笔已登记待确认 → 确定性链路让位（账本单写面）。

    原先两条链路对同一条消息各写一遍：词表链路先入账、LLM 抽取链路再登记待确认，
    用户一点确认就落第二笔（实测 240 元牛杂：16:57 落一笔，17:10 确认后又落一笔）。
    金额一致才让位——金额对不上说明两条链路读到的不是同一笔，此时不拦。
    """
    deferred_amount = getattr(ctx, "ledger_pending_amount", None)
    if deferred_amount is None:
        return False
    if intent.action_type != "record_ledger_entry":
        return False
    amount = intent.params.get("amount_minor")
    if not isinstance(amount, int) or amount != deferred_amount:
        return False
    if ctx.trace is not None:
        ctx.trace.record(
            "action_planning",
            0.0,
            "deferred",
            reason="ledger_pending_confirmation",
            amount_minor=amount,
        )
    return True


async def run_action_planning(ctx: PostProcessContext) -> None:
    """V9 第 9 步：行动意图检出 → 六闸门 → 计划 → 执行 → 四通道整合。

    V2.4.0 TOOL-004：步骤**内部**增强（不新增步骤、不改序列）——工具面子闸开启时
    先投影工具面，把 `surface.tool_ids` 作为 capability 候选喂给既有决策管线（工具候选
    只参与六维评分与审计落库，前台 `chat_response` 恒胜出），投影结果随既有
    `trace.record()` 进 `runtime_traces.steps`。子闸关闭时零行为差异。

    V2.4.0 TOOL-005：同样只做步骤**内部**增强——权限闸开启时先检出确认意图（确定性词表 +
    问句守卫，零新增 LLM），命中则在既有步骤内处理确认轮次并提前返回；未命中或闸门关闭时
    行为与 TOOL-004 一致。确认话术以 `record.gate_reason=pending_confirmation` 的行动记录
    进入下一轮既有 `ActionContext` 回复素材（本步骤不改序列、不新增步骤）。
    """
    if await _run_confirmation_round(ctx):
        return

    action_intent = ctx.action_intent
    if action_intent is None:
        return
    if isinstance(action_intent, dict):
        try:
            action_intent = ActionIntent.model_validate(action_intent)
        except Exception:
            logger.exception("行动意图反序列化失败，跳过第 9 步")
            return
    if _defer_to_ledger_pending(ctx, action_intent):
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
        surface_extra = _observe_tool_surface(ctx, goal_id)
        record = await _run(
            ctx.user_id,
            action_intent,
            session_id=ctx.session_id,
            goal_id=goal_id,
        )
        surface_extra.update(_observe_pending_confirmation(record))
        surface_extra.update(_observe_tool_evidence(ctx))
        if ctx.trace is not None:
            ctx.trace.record(
                "action_planning",
                (time.perf_counter() - started) * 1000,
                **surface_extra,
            )
    except Exception:
        logger.exception("行动规划步骤异常（双保险，不应触达）")
        if ctx.trace is not None:
            ctx.trace.record(
                "action_planning", 0.0, "error", error="action planning crashed"
            )


async def _run_confirmation_round(ctx: PostProcessContext) -> bool:
    """确认轮次检出与执行（TOOL-005 §2.3 步骤④）；未命中返回 False（按普通对话处理）。"""
    started = time.perf_counter()
    try:
        from app.application.action_engine import run_confirmation_round
        from app.services.tool.confirmation import (
            get_confirmation_detector,
            get_confirmation_service,
        )

        pending = get_confirmation_service().pending(ctx.user_id)
        if not pending:
            return False
        detected = get_confirmation_detector().detect(ctx.user_input, pending)
        if detected is None:
            return False
        request_id, verb = detected
        record = await run_confirmation_round(
            ctx.user_id, request_id, approved=verb == "approve", session_id=ctx.session_id
        )
        _record_confirmation_trace(ctx, started, request_id, verb, record)
        return True
    except Exception:
        logger.exception("确认轮次处理失败，降级为普通对话")
        return False


def _record_confirmation_trace(
    ctx: PostProcessContext, started: float, request_id: str, verb: str, record
) -> None:
    """确认轮次的观测面（独立容错：记账失败不影响"本轮已被消费"的事实）。"""
    if ctx.trace is None:
        return
    try:
        ctx.trace.record(
            "confirmation_round",
            (time.perf_counter() - started) * 1000,
            "ok",
            request_id=request_id,
            verb=verb,
            record_id=None if record is None else record.id,
            record_status=None if record is None else record.status,
        )
    except Exception:
        logger.exception("确认轮次 trace 记账失败")


def _observe_pending_confirmation(record) -> dict:
    """确认态观测（TOOL-005 §2.3）：话术随既有 `trace.record()` 进回复素材与观测面。"""
    if record is None or getattr(record, "gate_reason", None) != "pending_confirmation":
        return {}
    result = record.result or {}
    return {
        "pending_confirmation": {
            "record_id": record.id,
            "tool_id": (record.steps[0].get("tool_id") if record.steps else None),
            "prompt": result.get("error"),
        }
    }


def _observe_tool_evidence(ctx: PostProcessContext) -> dict:
    """工具证据反思接线（TOOL-009 §2.3）：只读 `action_records` 投影喂 reinforce 计数。

    接线失败记日志、不影响行动规划（与 REF-003 既有接线同款纪律）。
    """
    try:
        fired = reflection_triggers.observe_tool_evidence_from_records(
            ctx.user_id, trace=ctx.trace
        )
    except Exception:
        logger.exception("工具证据反思接线失败，不影响行动规划")
        return {}
    if not fired:
        return {}
    return {"tool_evidence_reinforce": fired}


def _observe_tool_surface(ctx: PostProcessContext, goal_id: str | None) -> dict:
    """第 9 步内部工具面观测（失败不影响本步骤）。"""
    settings = get_settings()
    try:
        from app.application.agent_runtime.models import RUN_KIND_FOREGROUND_CHAT
        from app.services.tool.context import ToolContext
        from app.services.tool.registry import get_tool_registry
        from app.services.tool.surface import ToolSurfaceResolver

        registry = get_tool_registry()
        now = timeutil.now()
        surface = ToolSurfaceResolver(registry, settings).resolve(
            RUN_KIND_FOREGROUND_CHAT,
            ToolContext(
                user_id=ctx.user_id,
                now=now,
                settings=settings,
                run_kind=RUN_KIND_FOREGROUND_CHAT,
                run_id=getattr(ctx.trace, "request_id", None),
                source="conversation",
            ),
        )
        audit = _run_tool_decision(ctx, surface, goal_id, now)
        _persist_tool_decision(ctx, surface, audit)
        return {
            "tool_surface": {
                "run_kind": surface.run_kind,
                "surface_hash": surface.surface_hash,
                "tool_ids": list(surface.tool_ids),
                "excluded": [dict(item) for item in surface.excluded],
            },
            "tool_winner": None if audit is None else _audit_winner(audit),
        }
    except Exception:
        logger.exception("工具面投影失败，跳过（不影响行动规划）")
        return {}


def _run_tool_decision(
    ctx: PostProcessContext, surface, goal_id: str | None, now: datetime
) -> dict | None:
    """把工具面作为 capability 候选接入既有决策管线（纯评分 + 审计；不改变前台回复）。"""
    from app.engines import decision as decision_pipeline

    if not surface.tool_ids:
        return None
    result = decision_pipeline.run_pipeline(
        capabilities=list(surface.tool_ids),
        chat_response=True,
        chat_response_intention=getattr(
            getattr(ctx, "intention", None), "intention", None
        ),
        chat_response_goal_id=goal_id,
        run=None,
        now=now,
    )
    audit = result.audit
    audit["surface_hash"] = surface.surface_hash
    audit["winner"] = result.winner.source if result.winner is not None else None
    return audit


def _audit_winner(audit: dict) -> str | None:
    winner = next(
        (item for item in audit.get("candidates", []) if item.get("won")),
        None,
    )
    if winner is None:
        return None
    payload = winner.get("tool_id") or winner.get("source")
    return payload


def _persist_tool_decision(ctx: PostProcessContext, surface, audit: dict | None) -> None:
    """工具候选审计落既有 `decision_records`（kind 复用既有值域，零迁移）。"""
    if audit is None:
        return
    from app.application.observability import on_decision
    from app.models.observability import DecisionKind, DecisionRecord

    on_decision(
        DecisionRecord(
            kind=DecisionKind.TURN_INTENTION,
            request_id=getattr(ctx.trace, "request_id", None),
            user_id=ctx.user_id,
            conversation_id=ctx.session_id,
            decision="tool_surface",
            reason=surface.surface_hash,
            input_snapshot={"tool_ids": list(surface.tool_ids)},
            candidates=audit,
        )
    )


async def run_ledger_extraction(ctx: PostProcessContext) -> None:
    """账本抽取候选（PLA-007）：零写库，只产候选并分流标记。失败不影响回答。"""
    try:
        from datetime import datetime

        from app.chains.ledger_extraction_chain import classify_extraction, extract_ledger
        from app.core.settings import get_settings

        extraction = extract_ledger(
            ctx.user_input,
            message_id=ctx.session_id,
            now=timeutil.now(),
            llm=ctx.llm,
        )
        decision = classify_extraction(
            extraction,
            min_confidence=get_settings().ledger_extraction_min_confidence,
        )
        if ctx.trace is not None:
            ctx.trace.record(
                "ledger_extraction",
                0.0,
                "ok" if decision != "ignore" else "skip",
                decision=decision,
                confidence=extraction.confidence,
            )
    except Exception:
        logger.exception("账本抽取失败，忽略本轮候选")


def _ledger_detected_payload(ctx: PostProcessContext) -> dict | None:
    """同轮**确定性词表链路**的解析（明细 + 已归一类目），交给待确认承载。

    返回 None = 本轮没有可直接入账的确定性解析（只有 LLM 认为是记账的情形），
    此时待确认沿用原有语义（纯 LLM 抽取）。
    """
    intent = ctx.action_intent
    if isinstance(intent, dict):
        try:
            intent = ActionIntent.model_validate(intent)
        except Exception:
            return None
    if intent is None or getattr(intent, "action_type", None) != "record_ledger_entry":
        return None
    params = getattr(intent, "params", None) or {}
    amount_minor = params.get("amount_minor")
    if not isinstance(amount_minor, int) or amount_minor <= 0:
        return None
    note = str(params.get("note") or "").strip()
    direction = str(params.get("direction") or "expense")
    detected: dict = {
        "amount_minor": amount_minor,
        "direction": direction,
        "note": note or None,
    }
    if not note:
        return detected
    from app.services.ledger import category as category_service
    from app.services.ledger import ensure_user_bootstrap

    ensure_user_bootstrap(ctx.user_id)
    kind = "income" if direction == "income" else "expense"
    result = category_service.normalize(ctx.user_id, note, kind=kind)
    if result.category_id:
        detected["category_name"] = result.category_name
    return detected


async def run_ledger_confirmation(ctx: PostProcessContext) -> None:
    """PLA-010 确认挂接：需澄清则登记待确认；超时清理。失败不影响回答。"""
    try:
        from datetime import datetime

        from app.services.ledger.confirmation import should_confirm
        from app.services.ledger.pending import expire_if_due, register_pending

        now = timeutil.now()
        expire_if_due(ctx.session_id, now=now)
        from app.chains.ledger_extraction_chain import extract_ledger

        extraction = extract_ledger(
            ctx.user_input,
            message_id=ctx.session_id,
            now=now,
            llm=ctx.llm,
        )
        request = should_confirm(
            extraction,
            now=now,
            source_ref=ctx.session_id,
        )
        if request is None:
            return
        detected = _ledger_detected_payload(ctx)
        record = register_pending(
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            request=request,
            extraction=extraction,
            detected=detected,
            now=now,
        )
        if detected is not None and detected.get("amount_minor") == request.amount_minor:
            ctx.ledger_pending_amount = int(detected["amount_minor"])
        if ctx.trace is not None:
            ctx.trace.record(
                "ledger_confirmation",
                0.0,
                "asked" if record is not None else "deduped",
                reason=request.reason,
                pending_key=request.pending_key,
                question=request.question,
                deferred_to_pending=ctx.ledger_pending_amount is not None,
            )
    except Exception:
        logger.exception("账本确认挂接失败，忽略本轮")


async def run_memory_evaluate(ctx: PostProcessContext) -> None:
    """收尾评估步（memory 域通道收敛第 3 批）：本轮世界/行动步骤投递的候选当轮转正。

    v2 评估原本只在第 5 步执行，而世界事件完结（第 10 步）与工具记忆投递
    （第 12 步内 `integrate_result`）产出的候选要等下一轮第 5 步才被评估——
    记忆可见性会比旁路直写时期晚一轮。本步补一次 `evaluate_pending`：
    无待评估候选时为一次空查询，有则同轮转正（REF 接线复用 `_evaluate_memory_candidates`，
    缓冲区二刷为空操作）。
    """
    started = time.perf_counter()
    try:
        await _evaluate_memory_candidates(ctx)
        if ctx.trace is not None:
            ctx.trace.record(
                "memory_evaluate_tail", (time.perf_counter() - started) * 1000
            )
    except Exception:
        logger.exception("记忆收尾评估失败，不影响本轮回答")
        if ctx.trace is not None:
            ctx.trace.record(
                "memory_evaluate_tail",
                (time.perf_counter() - started) * 1000,
                "error",
                error="memory evaluate tail failed",
            )


STEP_HANDLERS = (
    run_scene_update,
    run_state_update,
    run_goal_review,
    run_summary,
    run_memory_extract,
    run_ledger_extraction,
    run_ledger_confirmation,
    run_budget_observer,
    run_evaluation,
    run_world_update,
    run_character_action_sync,
    run_action_planning,
    run_memory_evaluate,
)


from app.core.runtime_state import get_user_write_lock, reset_user_write_locks


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
