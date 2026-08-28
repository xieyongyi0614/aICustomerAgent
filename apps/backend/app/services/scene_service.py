from app.core.settings import get_settings
from app.models.scene import PendingAction, SceneIntent, SceneState
from app.repositories import scene_state_repository


def load(session_id: str) -> SceneState:
    return scene_state_repository.get_scene_state(session_id)


def _pending_directive(pending: PendingAction, verb: str) -> str:
    return f"{verb}“{pending.action}”"


def resolve(
    intent: SceneIntent,
    state: SceneState,
    current_turn: int,
    pending_max_turns: int | None = None,
) -> tuple[SceneState, str | None]:
    max_turns = (
        pending_max_turns
        if pending_max_turns is not None
        else get_settings().scene_pending_max_turns
    )
    directives: list[str] = []
    pending = state.pending_action

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
    state: SceneState, action: str, current_turn: int
) -> SceneState:
    new_pending = PendingAction(action=action, status="pending", created_at_turn=current_turn)
    return state.model_copy(update={"pending_action": new_pending})
