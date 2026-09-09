import time
from datetime import datetime

from app.chains import scene_update_chain
from app.core.settings import get_settings
from app.models.scene import PendingAction, SceneActionDecision, SceneIntent, SceneState
from app.repositories import scene_state_repository

_FIELD_MAX_LENGTH = 50


def _idle_gap_text(state: SceneState, now: datetime) -> str:
    reference = state.last_active_at
    if reference is None:
        return "一段时间"
    delta = now - reference
    hours = delta.total_seconds() / 3600
    if hours >= 24:
        days = int(hours // 24)
        return f"{days}天" if days > 1 else "一天"
    if hours >= 1:
        return f"{int(hours)}个小时"
    return f"{max(int(delta.total_seconds() // 60), 1)}分钟"


def _stale_directive(state: SceneState, now: datetime) -> str | None:
    if not get_settings().scene_idle_reset_enabled:
        return None
    if state.last_active_at is None:
        return None
    gap = _idle_gap_text(state, now)
    return (
        f"距上次对话已过去{gap}，之前的场景活动与待办均已结束，"
        f"不要延续旧活动，自然承接当前对话"
    )


def load(session_id: str) -> SceneState:
    return scene_state_repository.get_scene_state(session_id)


def _pending_directive(pending: PendingAction, verb: str) -> str:
    return f"{verb}“{pending.action}”"


def _is_idle_expired(state: SceneState, now: datetime) -> bool:
    if not get_settings().scene_idle_reset_enabled or state.last_active_at is None:
        return False
    idle_hours = (now - state.last_active_at).total_seconds() / 3600
    return idle_hours >= get_settings().scene_idle_reset_hours


def resolve(
    intent: SceneIntent,
    state: SceneState,
    current_turn: int,
    pending_max_turns: int | None = None,
    now: datetime | None = None,
) -> tuple[SceneState, str | None]:
    current_now = now or datetime.now()
    directives: list[str] = []
    pending = state.pending_action
    if _is_idle_expired(state, current_now):
        stale = _stale_directive(state, current_now)
        if stale is not None:
            directives.append(stale)
        state = state.model_copy(
            update={"current_activity": None, "current_action": None}
        )
        if pending is not None and pending.status == "pending":
            pending = pending.model_copy(update={"status": "cancelled"})
    max_turns = (
        pending_max_turns
        if pending_max_turns is not None
        else get_settings().scene_pending_max_turns
    )

    if pending is not None and pending.status == "pending":
        age = current_turn - pending.created_at_turn
        if age >= max_turns:
            directives.append(
                f"用户之前的待完成动作“{pending.action}”已过期，不要再执行"
            )
            pending = pending.model_copy(update={"status": "cancelled"})

    if intent == "interrupt":
        if pending is not None and pending.status == "pending":
            directives.append(f"用户已取消“{pending.action}”，不要继续，自然接话")
            pending = pending.model_copy(update={"status": "cancelled"})
    elif intent == "correct_scene":
        if pending is not None and pending.status == "pending":
            directives.append(
                f"用户指出你之前的行为没完成，本轮必须先执行“{pending.action}”"
            )
    elif intent == "continue_scene":
        if pending is not None and pending.status == "pending":
            directives.append(
                _pending_directive(pending, "先完成待完成动作") + "，再自然回应"
            )
    elif intent == "request_action":
        directives.append("用户要求你做新的事，行动后记录新的待完成动作")

    new_state = state.model_copy(update={"pending_action": pending})
    return new_state, ("\n".join(directives) or None)


def apply_new_pending(
    state: SceneState, action: str, current_turn: int, now: datetime | None = None
) -> SceneState:
    new_pending = PendingAction(
        action=action,
        status="pending",
        created_at_turn=current_turn,
        created_at=now or datetime.now(),
    )
    return state.model_copy(update={"pending_action": new_pending})


def _truncate(text: str) -> str:
    return text[:_FIELD_MAX_LENGTH]


def update_scene_state(
    prev_state: SceneState,
    decision: SceneActionDecision | None,
    intent: SceneIntent,
    current_turn: int,
) -> SceneState:
    if decision is None:
        return prev_state
    next_state = prev_state.model_copy(deep=True)

    if decision.location is not None:
        next_state.location = _truncate(decision.location)
    if decision.current_activity is not None:
        next_state.current_activity = _truncate(decision.current_activity)
    if decision.current_action is not None:
        next_state.current_action = _truncate(decision.current_action)

    pending = next_state.pending_action

    if decision.new_pending_action is not None and intent == "request_action":
        next_state = apply_new_pending(
            next_state, _truncate(decision.new_pending_action), current_turn
        )
        pending = next_state.pending_action
    elif decision.new_pending_action is not None:
        return next_state

    if (
        decision.pending_action_done
        and pending is not None
        and pending.status == "pending"
    ):
        next_state = next_state.model_copy(
            update={
                "pending_action": pending.model_copy(update={"status": "completed"})
            }
        )

    return next_state


async def update_and_persist(
    session_id: str,
    prev_state: SceneState,
    intent: SceneIntent,
    user_input: str,
    ai_reply: str,
    current_turn: int,
    llm=None,
    trace=None,
) -> SceneState:
    started = time.perf_counter()
    decision = await scene_update_chain.detect(user_input, ai_reply, prev_state, llm=llm)
    if trace is not None:
        elapsed = (time.perf_counter() - started) * 1000
        trace.record("scene_update", elapsed, "degraded" if decision is None else "ok")
    next_state = update_scene_state(prev_state, decision, intent, current_turn)
    scene_state_repository.upsert_scene_state(session_id, next_state)
    return next_state
