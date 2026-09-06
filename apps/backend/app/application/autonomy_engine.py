"""V7 AutonomyEngine（architecture.md §2 / scheduler.md §2）。

tick：候选用户枚举 → TriggerEvaluator → AutonomyPolicy → 入队 → Executor 同 tick 执行。
复用 V6 goal_service.select 与 V6.5 行为层，不绕行（architecture.md §4）。
"""

import logging
import time
import uuid
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.application import observability, world_engine
from app.models.autonomy import ProactiveAction, TriggerSignal
from app.models.observability import DecisionKind, DecisionRecord, TraceKind, bound_extra
from app.repositories import (
    conversation_repository,
    goal_repository,
    proactive_repository,
)
from app.services import (
    autonomy_policy,
    goal_service,
    proactive_executor,
    scene_service,
    state_service,
    trigger_evaluator,
)
from app.services.trace_collector import TurnTraceSession, get_trace_collector

logger = logging.getLogger(__name__)

_DATETIME_MIN = datetime(1970, 1, 1)
_ACTION_FACTS_CACHE: dict[str, dict] = {}


def _collect_action_facts(user_id: str) -> dict:
    from app.application.action_engine import collect_facts

    if not get_settings().action_enabled:
        _ACTION_FACTS_CACHE.pop(user_id, None)
        return {}
    try:
        return collect_facts(user_id)
    except Exception:
        logger.exception("行动事实收集失败，返回空包")
        return {}


def _params_for_autonomy_action(action_type: str, now: datetime) -> dict:
    """自治产行动参数模板（autonomy-integration.md §4）；无模板返回空参。"""
    if action_type == "create_reminder":
        return {"content": "休息一下", "due_at": (now + timedelta(minutes=30)).isoformat()}
    return {}


def _autonomy_action_today(user_id: str, now: datetime) -> int:
    from app.repositories import action_repository

    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    records = action_repository.list_records(user_id, limit=200)
    return sum(
        1
        for r in records
        if r.source == "autonomy" and r.created_at is not None and r.created_at >= start
    )


async def _produce_autonomy_action(
    verdict, user_id: str, session_id: str, now: datetime
) -> bool:
    """自治产行动分支（autonomy-integration.md §4）：默认关，仅命中开启才求值。"""
    settings = get_settings()
    if not settings.autonomy_action_enabled:
        return False
    from app.character.asuna.action import PROACTIVE_ACTION_MAP
    from app.application.action_engine import run_action_planning
    from app.models.action import ActionIntent

    action_type = PROACTIVE_ACTION_MAP.get(verdict.intention or "")
    if action_type is None:
        return False
    if _autonomy_action_today(user_id, now) >= settings.autonomy_action_daily_limit:
        logger.info("自治产行动日额度已满：%s", user_id)
        return False
    intent = ActionIntent(
        action_type=action_type,
        confidence="confident",
        params=_params_for_autonomy_action(action_type, now),
        dedupe_key=f"autonomy:{action_type}:{now.date().isoformat()}",
    )
    record = await run_action_planning(
        user_id, intent, session_id=session_id, source="autonomy"
    )
    return record is not None


def _session_tail(messages, now: datetime) -> trigger_evaluator.SessionTail:
    last = messages[-1] if messages else None
    last_user = next((m for m in reversed(messages) if m.role == "human"), None)
    return trigger_evaluator.SessionTail(
        last_message_at=last.created_at if last is not None else None,
        last_message_role=last.role if last is not None else None,
        last_user_message_at=last_user.created_at if last_user is not None else None,
        last_user_message_id=str(last_user.id) if last_user is not None else None,
    )


def _snapshot_for(
    user_id: str, session_id: str, now: datetime, episode_start: datetime
):
    from app.application.chat_pipeline import active_generations
    from app.repositories import relationship_milestone_repository

    character, relationship = state_service.load_states(user_id)
    scene_state = scene_service.load(session_id)
    goals = goal_repository.list_active(user_id)
    late_night_start = get_settings().goal_late_night_start
    late_night_end = get_settings().goal_late_night_end
    late_night = now.hour >= late_night_start or now.hour < late_night_end
    selected = goal_service.select(
        goals,
        tension=relationship.tension,
        user_emotion=state_service.load_last_user_emotion(user_id),
        character_mood=character.mood,
        character_intensity=character.intensity,
        scene_pending=False,
        late_night=late_night,
    )
    last_proactive_at, attempts = proactive_repository.aggregate_episode(
        user_id,
        episode_start=episode_start,
    )
    try:
        unlocks = relationship_milestone_repository.list_unlocks(user_id)
    except Exception:
        unlocks = ()
    relationship_patterns: tuple[str, ...] = ()
    try:
        from app.services import relationship_patterns as relationship_pattern_service

        patterns, _ = relationship_pattern_service.read_relationship_patterns(user_id)
        relationship_patterns = tuple(pattern.key for pattern in patterns)
    except Exception:
        logger.exception("关系模式读取失败，闸门参考为空")
    return autonomy_policy.PolicySnapshot(
        generating=active_generations.get(user_id, False),
        has_active_action=proactive_repository.has_non_terminal(user_id),
        last_proactive_at=last_proactive_at,
        attempt_count=attempts,
        intimacy=relationship.intimacy,
        tension=relationship.tension,
        mood=character.mood,
        current_activity=(
            scene_state.current_activity if scene_state is not None else None
        ),
        selected_goal_type=selected.goal.type if selected.goal is not None else None,
        goal_degraded=selected.goal is None,
        extra_flags={"goal_id": selected.goal.id if selected.goal is not None else None},
        world_facts=world_engine.collect_facts(user_id),
        action_facts=_collect_action_facts(user_id),
        respect=getattr(relationship, "respect", 0.6),
        comfort=getattr(relationship, "comfort", 0.6),
        conflict_status=getattr(relationship, "conflict_status", "none") or "none",
        neglect_active=bool(getattr(relationship, "neglect_active", False)),
        unlocks=unlocks,
        trust=relationship.trust,
        stage=relationship.stage,
        relationship_patterns=relationship_patterns,
    )


def _build_action(
    verdict, session_id: str, now: datetime
) -> ProactiveAction:
    return ProactiveAction(
        id=uuid.uuid4().hex,
        user_id=verdict.trigger.user_id,
        session_id=session_id,
        trigger_type=verdict.trigger.type,
        dedupe_key=verdict.trigger.dedupe_key,
        goal_id=verdict.goal_id,
        intention=verdict.intention or "check_in",
        reason=verdict.reason,
        created_at=now,
        updated_at=now,
    )


def reset_episode(user_id: str) -> None:
    """用户发言开启新 episode；预留钩子位（dedupe 幂等由 repository 兜底）。"""


def _decision_record(
    verdict, signal, snapshot, user_id: str, session_id: str, action_id=None, outcome=None
) -> DecisionRecord:
    payload, _ = bound_extra(
        {
            "generating": snapshot.generating,
            "has_active_action": snapshot.has_active_action,
            "last_proactive_at": (
                str(snapshot.last_proactive_at) if snapshot.last_proactive_at else None
            ),
            "attempt_count": snapshot.attempt_count,
            "intimacy": snapshot.intimacy,
            "tension": snapshot.tension,
            "mood": snapshot.mood,
            "current_activity": snapshot.current_activity,
            "selected_goal_type": snapshot.selected_goal_type,
            "goal_degraded": snapshot.goal_degraded,
            "goal_id": snapshot.extra_flags.get("goal_id"),
            "relationship_patterns": list(snapshot.relationship_patterns),
        },
        get_settings().observability_step_extra_max_chars,
    )
    return DecisionRecord(
        kind=DecisionKind.PROACTIVE_AUTONOMY,
        user_id=user_id,
        conversation_id=session_id,
        action_id=action_id,
        trigger=signal.type,
        input_snapshot=payload,
        decision=verdict.decision,
        reason=verdict.reason,
    )


def _record_decision(**kwargs) -> None:
    try:
        observability.on_decision(_decision_record(**kwargs))
    except Exception:
        logger.exception("主动决策记录失败，已忽略")


async def _process_user(user_id: str, llm, now: datetime) -> str | None:
    conversation = conversation_repository.get_latest_for_user(user_id)
    if conversation is None:
        return None
    messages = conversation_repository.get_recent_messages(conversation.id, limit=5)
    tail = _session_tail(messages, now)
    _, attempts = proactive_repository.aggregate_episode(
        user_id,
        episode_start=tail.last_user_message_at or _DATETIME_MIN,
    )
    due_action = trigger_evaluator.poll_due_actions(user_id, now)
    if due_action is not None:
        signal: TriggerSignal | None = due_action
    else:
        followup = trigger_evaluator.poll_due_followup(user_id, now)
        if followup is not None:
            signal = followup
        else:
            signal = trigger_evaluator.evaluate_inactivity(
                tail,
                user_id,
                episode_attempts=attempts,
                now=now,
            )
    if signal is None:
        return None

    started = time.perf_counter()
    trace = TurnTraceSession()
    snapshot = _snapshot_for(
        user_id,
        conversation.id,
        now,
        episode_start=tail.last_user_message_at or _DATETIME_MIN,
    )
    verdict = autonomy_policy.evaluate(signal, snapshot, get_settings(), now)
    trace.record(
        "autonomy_policy",
        (time.perf_counter() - started) * 1000,
        verdict.decision,
        reason=verdict.reason,
        goal_id=verdict.goal_id,
        intention=verdict.intention,
    )
    logger.info(
        "主动行为裁决：user=%s decision=%s reason=%s",
        user_id,
        verdict.decision,
        verdict.reason,
    )
    if verdict.decision != "act" or verdict.goal_id is None:
        _record_decision(
            verdict=verdict,
            signal=signal,
            snapshot=snapshot,
            user_id=user_id,
            session_id=conversation.id,
        )
        observability.on_turn_finished(
            trace,
            turn_id=None,
            user_id=user_id,
            session_id=conversation.id,
            kind=TraceKind.AUTONOMY_TICK,
            drain_background=False,
        )
        return None

    produced_action = await _produce_autonomy_action(verdict, user_id, conversation.id, now)
    if produced_action:
        _record_decision(
            verdict=verdict,
            signal=signal,
            snapshot=snapshot,
            user_id=user_id,
            session_id=conversation.id,
        )
        observability.on_turn_finished(
            trace,
            turn_id=None,
            user_id=user_id,
            session_id=conversation.id,
            kind=TraceKind.AUTONOMY_TICK,
            drain_background=False,
        )
        return None

    action = _build_action(verdict, conversation.id, now)
    enqueued = proactive_repository.enqueue(action)
    _record_decision(
        verdict=verdict,
        signal=signal,
        snapshot=snapshot,
        user_id=user_id,
        session_id=conversation.id,
        action_id=action.id,
        outcome=None if enqueued else "enqueue_failed",
    )
    if not enqueued:
        return None
    active = proactive_repository.get_active(user_id, now)
    if active is None or active.id != action.id:
        return None
    observability_token = observability.current_trace.set(trace)
    try:
        delivered = await proactive_executor.execute(
            active, llm=llm, trace=trace, now=now
        )
    finally:
        observability.current_trace.reset(observability_token)
    if delivered is not None and delivered.status == "delivered":
        collector = get_trace_collector()
        collector.attach(trace, str(delivered.message_id))
        observability.on_turn_finished(
            trace,
            turn_id=str(delivered.message_id),
            user_id=user_id,
            session_id=conversation.id,
            kind=TraceKind.PROACTIVE,
            action_id=action.id,
            drain_background=False,
        )
        if signal.type == "action_due":
            event_id = signal.context.get("event_id")
            if event_id:
                trigger_evaluator.mark_action_reported(user_id, event_id)
        return delivered.message_id
    observability.on_turn_finished(
        trace,
        turn_id=None,
        user_id=user_id,
        session_id=conversation.id,
        kind=TraceKind.PROACTIVE,
        action_id=action.id,
        drain_background=False,
    )
    return None


async def tick(user_ids: list[str] | None = None, llm=None, now: datetime | None = None) -> list[str]:
    now = now or datetime.now()
    users = user_ids or conversation_repository.list_user_ids()
    delivered_ids: list[str] = []
    for user_id in users:
        try:
            message_id = await _process_user(user_id, llm, now)
        except Exception:
            logger.exception("autonomy tick 用户评估失败：%s", user_id)
            continue
        if message_id is not None:
            delivered_ids.append(message_id)
    return delivered_ids
