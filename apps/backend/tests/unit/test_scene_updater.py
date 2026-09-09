from app.models.scene import PendingAction, SceneActionDecision, SceneState
from app.repositories import scene_state_repository
from app.services import scene_service


def _state(pending=None, location="客厅", current_action=None):
    return SceneState(
        session_id="s-1",
        turn_id=3,
        location=location,
        current_activity="休息",
        current_action=current_action,
        pending_action=pending,
    )


def _decision(**kwargs):
    base = {k: None for k in
            ("location", "current_activity", "current_action", "new_pending_action")}
    base.update({"pending_action_done": False, "pending_action_cancel": False})
    base.update(kwargs)
    return SceneActionDecision(**base)


def test_whitelist_merge_sets_only_present_fields():
    prev = _state()
    decision = _decision(location="厨房", current_activity="做饭")
    new_state = scene_service.update_scene_state(prev, decision, "chat", 4)
    assert new_state.location == "厨房"
    assert new_state.current_activity == "做饭"
    assert new_state.current_action is None


def test_merge_truncates_overlong_field():
    prev = _state()
    decision = SceneActionDecision.model_construct(location="x" * 100)
    new_state = scene_service.update_scene_state(prev, decision, "chat", 4)
    assert len(new_state.location) == 50


def test_merge_preserves_untouched_fields():
    prev = _state(pending=PendingAction(action="切西瓜", created_at_turn=1))
    new_state = scene_service.update_scene_state(prev, _decision(), "chat", 4)
    assert new_state.location == "客厅"
    assert new_state.current_activity == "休息"
    assert new_state.pending_action.action == "切西瓜"


def test_new_pending_applied_on_request_action():
    prev = _state()
    new_state = scene_service.update_scene_state(
        prev, _decision(new_pending_action="拿苹果"), "request_action", 4
    )
    assert new_state.pending_action is not None
    assert new_state.pending_action.action == "拿苹果"
    assert new_state.pending_action.created_at_turn == 4


def test_new_pending_dropped_on_non_request_intent():
    prev = _state()
    new_state = scene_service.update_scene_state(
        prev, _decision(new_pending_action="拿苹果"), "chat", 4
    )
    assert new_state.pending_action is None


def test_pending_action_done_moves_to_completed_history():
    prev = _state(pending=PendingAction(action="切西瓜", created_at_turn=1))
    new_state = scene_service.update_scene_state(
        prev, _decision(pending_action_done=True), "chat", 4
    )
    assert new_state.pending_action is None
    assert new_state.completed_actions == ["切西瓜"]
    assert new_state.current_action is None


def test_pending_done_keeps_new_current_action():
    prev = _state(
        pending=PendingAction(action="切西瓜", created_at_turn=1),
        current_action="切西瓜",
    )
    new_state = scene_service.update_scene_state(
        prev,
        _decision(pending_action_done=True, current_action="装碗"),
        "chat",
        4,
    )
    assert new_state.pending_action is None
    assert new_state.completed_actions == ["切西瓜"]
    assert new_state.current_action == "装碗"


def test_completed_history_dedupes_and_caps_window():
    prev = _state(pending=PendingAction(action="端碗", created_at_turn=1))
    prev = prev.model_copy(update={"completed_actions": ["端碗", "煮面", "摆桌"]})
    new_state = scene_service.update_scene_state(
        prev, _decision(pending_action_done=True), "chat", 4
    )
    assert new_state.completed_actions == ["煮面", "摆桌", "端碗"]
    assert len(new_state.completed_actions) == 3


def test_current_action_done_clears_current_action():
    prev = _state(current_action="端碗")
    new_state = scene_service.update_scene_state(
        prev, _decision(current_action_done=True), "chat", 4
    )
    assert new_state.current_action is None


def test_current_action_done_defaults_false_for_legacy_decisions():
    decision = SceneActionDecision.model_construct(location="厨房")
    assert decision.current_action_done is False
    prev = _state(current_action="端碗")
    new_state = scene_service.update_scene_state(prev, decision, "chat", 4)
    assert new_state.current_action == "端碗"


def test_updater_does_not_complete_cancelled_pending():
    prev = _state(pending=PendingAction(
        action="切西瓜", status="cancelled", created_at_turn=1))
    new_state = scene_service.update_scene_state(
        prev, _decision(pending_action_done=True), "chat", 4
    )
    assert new_state.pending_action is not None
    assert new_state.pending_action.status == "cancelled"
    assert new_state.completed_actions == []


def test_none_decision_keeps_previous_state():
    prev = _state(pending=PendingAction(action="切西瓜", created_at_turn=1))
    new_state = scene_service.update_scene_state(prev, None, "chat", 4)
    assert new_state == prev


async def test_update_and_persist_round_trip(db_session_factory, fake_llm):
    llm = fake_llm(
        structured_responses={
            "SceneActionDecision": {
                "location": "厨房",
                "current_activity": None,
                "current_action": "切西瓜",
                "new_pending_action": None,
                "pending_action_done": False,
                "pending_action_cancel": False,
            }
        }
    )
    prev = _state()
    new_state = await scene_service.update_and_persist(
        "s-1", prev, "chat", "好的", "*把西瓜切开*", 4, llm=llm
    )
    assert new_state.location == "厨房"

    loaded = scene_state_repository.get_scene_state("s-1")
    assert loaded.location == "厨房"
    assert loaded.current_action == "切西瓜"


async def test_update_and_persist_keeps_prev_on_chain_failure(
    db_session_factory, fake_llm
):
    llm = fake_llm(raise_exc=RuntimeError("boom"))
    prev = _state(location="客厅")
    new_state = await scene_service.update_and_persist(
        "s-1", prev, "chat", "好的", "回话", 4, llm=llm
    )
    assert new_state.location == "客厅"
    loaded = scene_state_repository.get_scene_state("s-1")
    assert loaded.location == "客厅"
