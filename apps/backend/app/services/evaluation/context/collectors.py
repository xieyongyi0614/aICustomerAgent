"""V7.5 评估上下文收集器（evaluation-model.md §4 / architecture.md §2①）。

从 PostProcessContext 与既有仓储切片构造 EvaluationContext 的各切片；
只读、零写操作，任一切片缺失容错（None/空值，不抛）。
"""

import logging
from datetime import datetime

from app.core.settings import get_settings
from app.models.behavior_strategy import ActionBudget
from app.engines import behavior as behavior_engine
from app.services.conversation import state as state_service
from app.services.conversation import service as conversation_service
from app.repositories import (
    decision_repository,
    llm_call_repository,
    loop_run_repository,
    outbox_repository,
    proactive_repository,
    trigger_registry_repository,
    goal_repository,
    action_repository,
    world_repository,
    emotion_history_repository,
    character_state_repository,
    relationship_repository,
)

from app.services.evaluation.context.slices import (
    ActionSlice,
    BehaviorSlice,
    DIGEST_MEMORIES,
    DIGEST_MEMORY_CHARS,
    DIGEST_REPLY_CHARS,
    DIGEST_RECENT_CHARS,
    DIGEST_RECENT_MESSAGES,
    DIGEST_USER_MESSAGE_CHARS,
    EmotionSlice,
    EvaluationContext,
    GoalLifecycleRef,
    GoalPlanRef,
    GoalRef,
    GoalSlice,
    LifeLoopProactiveRef,
    LifeLoopRunRef,
    LifeLoopSlice,
    LifeLoopTriggerRef,
    MemoryRef,
    ProactiveSlice,
    RecentMessage,
    RelationshipSlice,
    RECENT_TURNS_FOR_WINDOW,
    StateSlice,
    _clip,
)

logger = logging.getLogger(__name__)

def collect_life_loop_slice(
    user_id: str | None = None,
    now: datetime | None = None,
    window_hours: float = 24.0,
) -> LifeLoopSlice:
    """从 loop_runs / trigger_registry / proactive_actions / llm_call_records /
    outbox_events 汇集审计切片（纯只读）；stale/溯源判定在此计算，规则保持纯函数。"""
    from datetime import timedelta


    now = now or datetime.now()
    settings = get_settings()
    cutoff = now - timedelta(hours=window_hours)
    stale_cutoff = now - timedelta(
        seconds=2 * settings.job_running_timeout
    )
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    runs = []
    for run in loop_run_repository.list_recent(user_id=user_id, limit=200):
        if run.started_at is not None and run.started_at < cutoff:
            continue
        steps = run.steps or []
        aborted_with_reason = any(
            s.get("step") == "abort" or s.get("error")
            for s in steps
            if s.get("status") == "error"
        )
        runs.append(
            LifeLoopRunRef(
                run_id=run.id,
                kind=run.kind,
                status=run.status,
                reason=run.reason or "",
                step_names=[s.get("step", "") for s in steps],
                llm_call_count=run.llm_call_count or 0,
                budget_degraded=(run.budget_state or {}).get("status") == "degraded",
                aborted_with_reason=aborted_with_reason or run.status != "aborted",
            )
        )

    triggers = []
    for trigger in trigger_registry_repository.list_recent(user_id=user_id, limit=200):
        triggers.append(
            LifeLoopTriggerRef(
                trigger_key=trigger.trigger_key,
                trigger_type=trigger.trigger_type,
                status=trigger.status,
                attempt_count=trigger.attempt_count,
                stale=(
                    trigger.status in ("due", "fired")
                    and trigger.updated_at is not None
                    and trigger.updated_at <= stale_cutoff
                ),
                cancelled_without_reason=(
                    trigger.status == "cancelled" and not trigger.last_error
                ),
            )
        )

    delivered = []
    for row in proactive_repository.list_since(cutoff):
        if row.user_id != user_id or row.status != "delivered":
            continue
        # 溯源 = decision_records 存在该 action 的 PROACTIVE_AUTONOMY 决策行
        decisions = decision_repository.get_by_action(row.id)
        provenanced = any(d.kind == "proactive_autonomy" for d in decisions)
        delivered.append(
            LifeLoopProactiveRef(
                action_id=row.id,
                trigger_type=row.trigger_type or "",
                provenanced=provenanced,
            )
        )

    usage = llm_call_repository.aggregate_usage_since(day_start)
    dead_letters = [
        r for r in outbox_repository.list_recent(status="failed", limit=100)
    ]
    return LifeLoopSlice(
        runs=runs,
        triggers=triggers,
        delivered_proactive=delivered,
        day_llm_calls=usage["calls"],
        day_llm_call_limit=settings.life_loop_daily_llm_call_budget,
        outbox_dead_letters=len(dead_letters),
    )


def collect_goal_slice(
    user_id: str | None = None,
    now: datetime | None = None,
    window_hours: float = 24 * 30.0,
) -> GoalSlice:
    """从 character_goals / goal_plans / decision_records 汇集 Goal 审计切片（纯只读）。"""
    from datetime import timedelta


    slice_ = GoalSlice()
    try:
        goals = (
            goal_repository.list_layered(user_id)
            if user_id is not None
            else []
        )
    except Exception:
        logger.exception("goal 切片读取失败，按空集处理")
        return slice_
    for goal in goals:
        slice_.goals.append(
            GoalRef(
                goal_id=goal.id,
                layer=goal.layer or "",
                domain=goal.domain or "",
                status=goal.status,
                horizon=goal.horizon,
                parent_goal_id=goal.parent_goal_id,
                failure_reason=goal.failure_reason,
                arbitration_state=goal.arbitration_state,
                created_at=goal.created_at,
                updated_at=goal.updated_at,
            )
        )
        for plan in goal_repository.list_plans(goal.id):
            slice_.plans.append(
                GoalPlanRef(
                    goal_id=goal.id,
                    version=plan.version,
                    status=plan.status,
                    sub_goal_statuses=[spec.status for spec in plan.sub_goals],
                    sub_goal_attempt_counts=[spec.attempt_count for spec in plan.sub_goals],
                    capabilities=sorted({spec.capability for spec in plan.sub_goals}),
                    rejection_reason=plan.rejection_reason,
                    updated_at=plan.updated_at,
                )
            )
    try:
        cutoff = (now or datetime.now()) - timedelta(hours=window_hours)
        for record in decision_repository.search(
            user_id=user_id, kind="goal_lifecycle", since=cutoff, limit=500
        ):
            slice_.lifecycles.append(
                GoalLifecycleRef(
                    goal_id=(record.input_snapshot or {}).get("goal_id", ""),
                    decision=record.decision,
                    reason=record.reason,
                    created_at=record.created_at,
                )
            )
    except Exception:
        logger.exception("goal lifecycle 记录读取失败，按空集处理")
    return slice_


def collect_turn_context(ctx) -> EvaluationContext:
    settings = get_settings()
    context = EvaluationContext(
        subject="turn",
        subject_id=str(getattr(ctx.trace, "turn_id", None) or ctx.current_turn or ""),
        session_id=ctx.session_id,
        user_id=ctx.user_id,
        mode=getattr(ctx.state, "mode", "default"),
        stage=getattr(ctx.state.relationship_state, "stage", "friend"),
        user_message=_clip(ctx.user_input, DIGEST_USER_MESSAGE_CHARS),
        reply=_clip(ctx.ai_reply, DIGEST_REPLY_CHARS),
        request_id=getattr(ctx.trace, "request_id", "") or "",
    )
    context.recent_messages = _collect_recent_messages(ctx)
    context.injected_memories = _collect_injected_memories(ctx.state)
    context.emotion = _collect_emotion(ctx)
    context.state = _collect_state(ctx.user_id, ctx.state)
    if ctx.behavior is not None:
        context.behavior = _collect_behavior(ctx)
        context.behavior_history = _collect_behavior_history(ctx.session_id, settings)
    context.world = _collect_world(ctx.user_id)
    context.relationship = _collect_relationship(ctx.user_id)
    context.action = _collect_action(ctx.user_id)
    return context


def _collect_action(user_id: str) -> ActionSlice | None:
    """V9 行动审计切片（只读）：缺席为 None = action 规则全部跳过。"""
    try:
        records = action_repository.list_records(user_id, limit=20)
        if not records:
            return None
        return ActionSlice(
            records=[r.model_dump(mode="json") for r in records],
        )
    except Exception:
        logger.exception("行动切片读取失败，action 规则降级")
        return None


def _collect_relationship(user_id: str) -> RelationshipSlice | None:
    """V8.5 关系演化审计切片（内存审计，缺席为 None = 规则跳过）。"""
    try:
        audit = state_service.get_relationship_audit(user_id)
    except Exception:
        logger.exception("关系审计切片读取失败，relationship 规则降级")
        return None
    if not audit:
        return None
    return RelationshipSlice(
        before=_state_dims(audit.get("before")),
        after=_state_dims(audit.get("after")),
        applied=_delta_dims(audit.get("applied")),
        truncated=dict(audit.get("truncated") or {}),
        day_positive=_delta_dims(audit.get("day_positive")),
        day_negative=_delta_dims(audit.get("day_negative")),
        events=list(audit.get("events") or []),
        signal_present=bool(audit.get("signal_present")),
        comfort_drift=float(audit.get("comfort_drift") or 0.0),
        conflict_status=str(
            getattr(audit.get("after"), "conflict_status", "none") or "none"
        ),
    )


_RELATIONSHIP_DIMENSIONS = ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")


def _state_dims(state) -> dict | None:
    if state is None:
        return None
    return {dim: float(getattr(state, dim, 0.0)) for dim in _RELATIONSHIP_DIMENSIONS}


def _delta_dims(delta) -> dict | None:
    if delta is None:
        return None
    return {dim: float(getattr(delta, dim, 0.0)) for dim in _RELATIONSHIP_DIMENSIONS}


def _collect_world(user_id: str) -> dict | None:
    """V8 世界事实切片（只读）：评估 World Consistency 规则用；缺席为 None。"""
    try:
        world = world_repository.get_world(user_id)
        if world is None:
            return None
        entities = world_repository.list_objects(world.world_id)
        return {
            "location": world.current_location,
            "objects": [
                {
                    "name": obj.name,
                    "state": obj.state,
                    "quantity": obj.quantity,
                    "status": obj.status.value,
                }
                for obj in entities
            ],
        }
    except Exception:
        logger.exception("世界切片读取失败，world 规则降级")
        return None


def _collect_recent_messages(ctx) -> list[RecentMessage]:
    try:
        history = conversation_service.load_window(ctx.session_id)
    except Exception:
        logger.exception("近期消息切片读取失败，digest 降级")
        return []
    emotion_rows = []
    try:
        emotion_rows = emotion_history_repository.list_recent(ctx.user_id, limit=RECENT_TURNS_FOR_WINDOW)
    except Exception:
        logger.exception("情绪史切片读取失败，mood 配对降级")
    moods = [row.mood_after for row in emotion_rows]
    recent: list[RecentMessage] = []
    ai_index = 0
    for message in reversed(history):
        mood_after = None
        if message.role == "ai" and ai_index < len(moods):
            mood_after = moods[ai_index]
            ai_index += 1
        recent.append(
            RecentMessage(
                role=message.role,
                content=_clip(message.content, DIGEST_RECENT_CHARS),
                mood_after=mood_after,
            )
        )
        if len(recent) >= DIGEST_RECENT_MESSAGES:
            break
    recent.reverse()
    return recent


def _collect_injected_memories(state) -> list[MemoryRef]:
    memories = getattr(state, "memories", None) or []
    refs = []
    for memory in memories[:DIGEST_MEMORIES]:
        refs.append(
            MemoryRef(
                id=str(getattr(memory, "id", "")),
                type=str(getattr(memory, "type", "")),
                content=_clip(getattr(memory, "content", ""), DIGEST_MEMORY_CHARS),
                importance=float(getattr(memory, "importance", 0.0) or 0.0),
            )
        )
    return refs


def _collect_emotion(ctx) -> EmotionSlice:
    try:
        rows = emotion_history_repository.list_recent(ctx.user_id, limit=1)
        state = character_state_repository.get_state(ctx.user_id)
        latest = rows[0] if rows else None
        event = ctx.analysis.emotion_event if ctx.analysis is not None else None
        return EmotionSlice(
            mood_before=getattr(latest, "mood_before", None),
            mood_after=getattr(latest, "mood_after", None),
            intensity=getattr(state, "intensity", None),
            event=getattr(event, "type", None),
            magnitude=getattr(event, "magnitude", None),
            cause=getattr(event, "cause", None) or None,
        )
    except Exception:
        logger.exception("情绪切片读取失败，digest 降级")
        return EmotionSlice()


def _collect_state(user_id: str, state) -> StateSlice:
    try:
        relationship = relationship_repository.get_relationship(user_id)
    except Exception:
        logger.exception("关系切片读取失败，digest 降级")
        relationship = None
    character = getattr(state, "character_state", None)
    return StateSlice(
        mood=getattr(character, "mood", None),
        energy=getattr(character, "energy", None),
        stage=getattr(relationship, "stage", None) or getattr(state.relationship_state, "stage", None),
        intimacy=getattr(relationship, "intimacy", None),
    )


def _collect_behavior(ctx) -> BehaviorSlice:
    directive = ctx.behavior
    budget: ActionBudget = directive.budget
    observation = behavior_engine.observe_budget(ctx.ai_reply, budget)
    return BehaviorSlice(
        max_action_desc=budget.max_action_desc,
        physical_contact=budget.physical_contact,
        emotion_expression=budget.emotion_expression,
        strategy=directive.strategy.strategy,
        observed_action_count=observation["action_count"],
        observed_contact_level=observation["contact_level"],
    )


def _collect_behavior_history(session_id: str, settings) -> list[list[str]]:
    """近窗每轮动作类别（behavior-evaluation.md §3.3 轻量重放，仅计数不重跑管线）。"""
    try:
        from app.services.evaluation.rules import lexicons

        history = conversation_service.load_window(session_id)
        ai_messages = [m.content for m in history if m.role == "ai" and m.content]
        window = ai_messages[-settings.evaluation_behavior_monotony_window :]
        return [lexicons.classify_actions(text) for text in window]
    except Exception:
        logger.exception("行为历史切片读取失败，单调窗降级")
        return []


def collect_proactive_context(action) -> EvaluationContext | None:
    """主动行为主体（autonomy-evaluation.md §1）：delivered 后由引擎调用，只读切片。"""
    if getattr(action, "status", "") != "delivered" or not getattr(
        action, "payload_text", None
    ):
        return None
    settings = get_settings()
    context = EvaluationContext(
        subject="proactive_action",
        subject_id=str(action.id),
        session_id=action.session_id,
        user_id=action.user_id,
        user_message="",
        reply=_clip(action.payload_text, DIGEST_REPLY_CHARS),
        request_id=str(action.id),
    )
    context.proactive = _collect_proactive_facts(action, settings)
    context.state = _collect_state(action.user_id, None)
    context.recent_messages = _collect_proactive_recent(action.session_id)
    return context


def _collect_proactive_facts(action, settings) -> ProactiveSlice:
    delivered_at = action.delivered_at
    previous_delivered_at = None
    episode_attempts = 1
    last_user_message_at = None
    try:
        history = proactive_repository.list_delivered_history(action.user_id, limit=10)
        earlier = [
            row
            for row in history
            if row.id != action.id and row.delivered_at is not None
        ]
        if earlier and delivered_at is not None:
            previous_delivered_at = earlier[0].delivered_at
            window_minutes = settings.autonomy_min_interval_minutes * 2
            episode_attempts = 1 + sum(
                1
                for row in earlier
                if (delivered_at - row.delivered_at).total_seconds() / 60
                <= window_minutes
            )
    except Exception:
        logger.exception("主动历史切片读取失败，时机审计降级")
    try:
        window = conversation_service.load_window(action.session_id, max_messages=10)
        human_messages = [m for m in window if m.role == "human"]
        if human_messages:
            last_user_message_at = human_messages[-1].created_at
    except Exception:
        logger.exception("会话尾部切片读取失败，时机审计降级")
    return ProactiveSlice(
        action_id=str(action.id),
        trigger_type=action.trigger_type,
        intention=action.intention,
        reason=action.reason,
        delivered_at=delivered_at,
        payload_text=_clip(action.payload_text or "", DIGEST_REPLY_CHARS),
        previous_delivered_at=previous_delivered_at,
        last_user_message_at=last_user_message_at,
        episode_attempts=episode_attempts,
    )


def _collect_proactive_recent(session_id: str) -> list[RecentMessage]:
    try:
        window = conversation_service.load_window(
            session_id, max_messages=DIGEST_RECENT_MESSAGES
        )
    except Exception:
        logger.exception("主动近期消息切片读取失败，digest 降级")
        return []
    return [
        RecentMessage(role=m.role, content=_clip(m.content, DIGEST_RECENT_CHARS))
        for m in window
    ][-DIGEST_RECENT_MESSAGES:]

