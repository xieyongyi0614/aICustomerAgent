import pytest
from pydantic import ValidationError

from app.models.scene import (
    ActionStatus,
    PendingAction,
    SceneActionDecision,
    SceneIntent,
    SceneIntentResult,
    SceneState,
)

SCENE_INTENTS = (
    "chat",
    "request_action",
    "continue_scene",
    "correct_scene",
    "interrupt",
    "question",
    "emotional",
)

ACTION_STATUSES = ("pending", "completed", "cancelled", "superseded")


def test_scene_intent_has_seven_values():
    assert len(SceneIntent.__args__) == 7
    assert set(SceneIntent.__args__) == set(SCENE_INTENTS)


def test_action_status_has_four_values():
    assert set(ActionStatus.__args__) == set(ACTION_STATUSES)


def test_scene_state_defaults_are_empty():
    state = SceneState(session_id="s-1")
    assert state.turn_id == 0
    assert state.location is None
    assert state.current_activity is None
    assert state.current_action is None
    assert state.pending_action is None
    assert state.scene_mood is None


def test_pending_action_defaults_to_pending():
    action = PendingAction(action="把西瓜拿给用户")
    assert action.status == "pending"
    assert action.created_at_turn == 0


def test_scene_state_persistent_dump_excludes_mood():
    state = SceneState(
        session_id="s-1",
        turn_id=3,
        location="客厅",
        current_activity="休息",
        current_action="切西瓜",
        pending_action=PendingAction(action="把西瓜拿给用户", created_at_turn=2),
        scene_mood="relaxed",
    )
    data = state.persistent_dump()
    assert "scene_mood" not in data
    assert data["location"] == "客厅"
    assert data["pending_action"]["status"] == "pending"
    assert state.model_dump()["scene_mood"] == "relaxed"


def test_scene_intent_result_defaults():
    result = SceneIntentResult(intent="chat")
    assert result.confidence == 0.0
    assert result.reason == ""


def test_scene_intent_result_rejects_unknown_intent():
    with pytest.raises(ValidationError):
        SceneIntentResult(intent="dancing")


def test_scene_state_rejects_overlong_fields():
    with pytest.raises(ValidationError):
        SceneState(session_id="s-1", location="x" * 51)


def test_pending_action_rejects_overlong_action():
    with pytest.raises(ValidationError):
        PendingAction(action="x" * 51)


def test_scene_action_decision_defaults():
    decision = SceneActionDecision()
    assert decision.location is None
    assert decision.new_pending_action is None
    assert decision.pending_action_done is False
    assert decision.pending_action_cancel is False


def test_scene_action_decision_rejects_overlong_field():
    with pytest.raises(ValidationError):
        SceneActionDecision(current_action="x" * 51)


@pytest.mark.parametrize("intent", SCENE_INTENTS)
def test_scene_intent_accepts_all_valid_values(intent):
    result = SceneIntentResult(intent=intent)
    assert result.intent == intent


@pytest.mark.parametrize("status", ACTION_STATUSES)
def test_action_status_accepts_each_valid_status(status):
    action = PendingAction(action="切西瓜", status=status)
    assert action.status == status


def test_action_status_rejects_invalid_status():
    with pytest.raises(ValidationError):
        PendingAction(action="切西瓜", status="abandoned")


def test_pending_action_requires_action():
    with pytest.raises(ValidationError):
        PendingAction()


def test_scene_state_full_model_dump():
    state = SceneState(
        session_id="s-1",
        turn_id=5,
        location="客厅",
        current_activity="休息",
        current_action="切西瓜",
        pending_action=PendingAction(
            action="把西瓜拿给用户", status="pending", created_at_turn=4
        ),
        scene_mood="relaxed",
    )
    data = state.model_dump()
    assert data["session_id"] == "s-1"
    assert data["turn_id"] == 5
    assert data["location"] == "客厅"
    assert data["pending_action"]["status"] == "pending"
    assert data["pending_action"]["created_at_turn"] == 4
    assert data["scene_mood"] == "relaxed"


def test_scene_action_decision_full_structured():
    decision = SceneActionDecision(
        location="厨房",
        current_activity="做饭",
        current_action="切西瓜",
        new_pending_action="把西瓜拿给用户",
        pending_action_done=True,
        pending_action_cancel=False,
    )
    data = decision.model_dump()
    assert data["location"] == "厨房"
    assert data["current_action"] == "切西瓜"
    assert data["new_pending_action"] == "把西瓜拿给用户"
    assert data["pending_action_done"] is True
    assert data["pending_action_cancel"] is False


def test_scene_action_decision_ignores_unknown_field():
    decision = SceneActionDecision(current_action="递西瓜", bogus_field="x")
    assert "bogus_field" not in decision.model_dump()
