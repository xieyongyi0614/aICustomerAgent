"""V7 AutonomyEngine（architecture.md §2 / scheduler.md §2）。

tick：候选用户枚举 → TriggerEvaluator → AutonomyPolicy → 入队 → Executor 同 tick 执行。
复用 V6 goal_service.select 与 V6.5 行为层，不绕行（architecture.md §4）。
"""

import logging
import time
import uuid
from datetime import datetime, timedelta

from app.core.settings import get_settings
from app.models.autonomy import ProactiveAction, TriggerSignal
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


def reset_seen_keys() -> None:
    _seen_dedupe_keys.clear()


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
    followup = trigger_evaluator.poll_due_followup(user_id, now)
    if followup is not None:
        signal: TriggerSignal | None = followup
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
        return None

    action = _build_action(verdict, conversation.id, now)
    if not proactive_repository.enqueue(action):
        return None
    active = proactive_repository.get_active(user_id, now)
    if active is None or active.id != action.id:
        return None
    delivered = await proactive_executor.execute(
        active, llm=llm, trace=trace, now=now
    )
    if delivered is not None and delivered.status == "delivered":
        collector = get_trace_collector()
        collector.attach(trace, str(delivered.message_id))
        return delivered.message_id
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
