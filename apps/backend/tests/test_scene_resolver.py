from app.models.scene import PendingAction, SceneState
from app.services import scene_service


def _state(pending=None):
    return SceneState(
        session_id="s-1",
        turn_id=4,
        location="客厅",
        pending_action=pending,
    )


def test_interrupt_cancels_pending():
    state = _state(PendingAction(action="切西瓜", created_at_turn=1))
    new_state, directive = scene_service.resolve("interrupt", state, 4)
    assert new_state.pending_action.status == "cancelled"
    assert directive is not None
    assert "取消" in directive


def test_correct_scene_keeps_pending_active():
    state = _state(PendingAction(action="切西瓜", created_at_turn=1))
    new_state, directive = scene_service.resolve("correct_scene", state, 4)
    assert new_state.pending_action.status == "pending"
    assert "必须先执行“切西瓜”" in directive


def test_continue_scene_injects_continuity_directive():
    state = _state(PendingAction(action="切西瓜", created_at_turn=1))
    new_state, directive = scene_service.resolve("continue_scene", state, 4)
    assert new_state.pending_action.status == "pending"
    assert "先完成待完成动作“切西瓜”" in directive


def test_expiry_cancels_stale_pending():
    state = _state(PendingAction(action="切西瓜", created_at_turn=1))
    new_state, directive = scene_service.resolve("chat", state, 7, pending_max_turns=5)
    assert new_state.pending_action.status == "cancelled"
    assert "过期" in directive


def test_chat_does_not_migrate_before_expiry():
    state = _state(PendingAction(action="切西瓜", created_at_turn=1))
    new_state, directive = scene_service.resolve("chat", state, 4)
    assert new_state.pending_action.status == "pending"
    assert directive is None


def test_question_does_not_migrate():
    state = _state(PendingAction(action="切西瓜", created_at_turn=1))
    new_state, directive = scene_service.resolve("question", state, 4)
    assert new_state.pending_action.status == "pending"
    assert directive is None


def test_request_action_adds_new_task_directive():
    state = _state()
    _, directive = scene_service.resolve("request_action", state, 4)
    assert directive is not None
    assert "要求你做新的事" in directive


def test_apply_new_pending_supersedes_old():
    state = _state(PendingAction(action="拿水", created_at_turn=1))
    new_state = scene_service.apply_new_pending(state, "拿苹果", 2)
    assert new_state.pending_action.action == "拿苹果"
    assert new_state.pending_action.status == "pending"
    assert new_state.pending_action.created_at_turn == 2


def test_apply_new_pending_when_none_exists():
    state = _state()
    new_state = scene_service.apply_new_pending(state, "切西瓜", 1)
    assert new_state.pending_action.action == "切西瓜"


def test_resolve_does_not_mutate_input_state():
    state = _state(PendingAction(action="切西瓜", created_at_turn=1))
    original_status = state.pending_action.status
    scene_service.resolve("interrupt", state, 4)
    assert state.pending_action.status == original_status
