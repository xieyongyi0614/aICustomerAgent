import pytest

from app.models.character_state import CharacterState
from app.models.emotion import TurnAnalysis
from app.models.goal import GOAL_DESCRIPTION_MAX_LENGTH
from app.models.relationship import RelationshipState
from app.models.scene import PendingAction, SceneState
from app.repositories import goal_repository
from app.services.goal import service as goal_service

USER = "u-policy"
SESSION = "s-policy"


def _analysis(**overrides) -> TurnAnalysis:
    payload = {
        "user_emotion": {"emotion": "neutral", "event": "daily"},
        "behavior": {"behavior": "normal_reply", "reason": ""},
        "emotion_event": {"type": "none", "magnitude": "normal", "confidence": 0.0},
        "relationship_event": {
            "type": "none",
            "magnitude": "normal",
            "confidence": 0.0,
        },
    }
    payload.update(overrides)
    return TurnAnalysis(**payload)


def _scene(pending_action: str | None = None, status: str = "pending") -> SceneState:
    pending = None
    if pending_action is not None:
        pending = PendingAction(
            action=pending_action, status=status, created_at_turn=1
        )
    return SceneState(session_id=SESSION, turn_id=1, pending_action=pending)


def _review(
    analysis=None,
    executed_intention=None,
    current_turn=10,
    character=None,
    relationship=None,
    scene=None,
):
    return goal_service.review(
        USER,
        SESSION,
        analysis or _analysis(),
        executed_intention,
        current_turn,
        character or CharacterState(),
        relationship or RelationshipState(),
        scene or _scene(),
    )


@pytest.fixture(autouse=True)
def _db(db_session_factory):
    yield


class TestSeeding:
    def test_first_review_seeds_persistent(self):
        changes = _review()
        assert changes.is_empty()
        active = goal_repository.list_active(USER)
        assert len(active) == 3
        assert all(g.horizon == "persistent" for g in active)
        assert all(g.source == "definition" for g in active)

    def test_reseed_idempotent_across_reviews(self):
        _review()
        _review(current_turn=11)
        assert len(goal_repository.list_active(USER)) == 3


class TestCreation:
    def test_conflict_event_creates_repair_goal(self):
        analysis = _analysis(
            relationship_event={
                "type": "conflict",
                "magnitude": "strong",
                "confidence": 0.9,
            }
        )
        changes = _review(
            analysis=analysis, relationship=RelationshipState(tension=0.6)
        )
        assert len(changes.created) == 1
        created = changes.created[0]
        assert created.type == "relationship"
        assert created.description == goal_service.GOAL_DESCRIPTION_REPAIR
        assert created.source == "policy"
        assert created.horizon == "current"
        assert created.expires_at_turn == 10 + 20

    def test_conflict_goal_creation_idempotent(self):
        analysis = _analysis(
            relationship_event={
                "type": "boundary_violation",
                "magnitude": "normal",
                "confidence": 0.9,
            }
        )
        _review(analysis=analysis, relationship=RelationshipState(tension=0.6))
        changes = _review(
            analysis=analysis,
            relationship=RelationshipState(tension=0.6),
            current_turn=11,
        )
        assert changes.created == []
        repairs = [
            g
            for g in goal_repository.list_active(USER)
            if g.description == goal_service.GOAL_DESCRIPTION_REPAIR
        ]
        assert len(repairs) == 1

    def test_low_tension_conflict_event_creates_nothing(self):
        analysis = _analysis(
            relationship_event={
                "type": "conflict",
                "magnitude": "normal",
                "confidence": 0.9,
            }
        )
        changes = _review(analysis=analysis)
        assert changes.created == []

    def test_fatigue_creates_companion_goal(self):
        analysis = _analysis(user_emotion={"emotion": "tired", "event": "daily"})
        changes = _review(analysis=analysis)
        assert len(changes.created) == 1
        assert changes.created[0].type == "user_care"
        assert changes.created[0].description == goal_service.GOAL_DESCRIPTION_COMPANION

    def test_suggest_rest_creates_rest_goal(self):
        changes = _review(executed_intention="suggest_rest")
        assert len(changes.created) == 1
        assert changes.created[0].description == goal_service.GOAL_DESCRIPTION_REST

    def test_pending_action_creates_scene_goal(self):
        changes = _review(scene=_scene("切西瓜"))
        assert len(changes.created) == 1
        created = changes.created[0]
        assert created.type == "scene"
        assert created.source == "scene"
        assert created.description == "完成切西瓜"

    def test_only_one_creation_per_turn(self):
        analysis = _analysis(
            user_emotion={"emotion": "tired", "event": "daily"},
            relationship_event={
                "type": "conflict",
                "magnitude": "strong",
                "confidence": 0.9,
            },
        )
        changes = _review(
            analysis=analysis,
            executed_intention="suggest_rest",
            scene=_scene("切西瓜"),
            relationship=RelationshipState(tension=0.6),
        )
        assert len(changes.created) == 1
        assert changes.created[0].type == "scene"

    def test_no_signal_creates_nothing(self):
        changes = _review()
        assert changes.created == []


class TestCompletion:
    def test_pending_action_completed_completes_scene_goal(self):
        _review(scene=_scene("切西瓜"))
        changes = _review(
            scene=_scene("切西瓜", status="completed"), current_turn=11
        )
        assert len(changes.completed) == 1
        assert changes.completed[0].type == "scene"

    def test_pending_action_cancelled_completes_scene_goal(self):
        _review(scene=_scene("切西瓜"))
        changes = _review(
            scene=_scene("切西瓜", status="cancelled"), current_turn=11
        )
        assert len(changes.completed) == 1

    def test_superseded_scene_goal_cancelled(self):
        _review(scene=_scene("切西瓜"))
        changes = _review(scene=_scene("倒水"), current_turn=11)
        assert len(changes.cancelled) == 1
        assert changes.cancelled[0].description == "完成切西瓜"

    def test_repair_goal_completes_on_tension_drop(self):
        analysis = _analysis(
            relationship_event={
                "type": "conflict",
                "magnitude": "strong",
                "confidence": 0.9,
            }
        )
        _review(analysis=analysis, relationship=RelationshipState(tension=0.6))
        changes = _review(
            relationship=RelationshipState(tension=0.2), current_turn=11
        )
        assert len(changes.created) == 0
        assert len(changes.completed) == 1
        assert changes.completed[0].description == goal_service.GOAL_DESCRIPTION_REPAIR

    def test_repair_goal_cancelled_on_partial_recovery(self):
        analysis = _analysis(
            relationship_event={
                "type": "conflict",
                "magnitude": "strong",
                "confidence": 0.9,
            }
        )
        _review(analysis=analysis, relationship=RelationshipState(tension=0.6))
        changes = _review(
            relationship=RelationshipState(tension=0.4), current_turn=11
        )
        assert len(changes.created) == 0
        assert len(changes.cancelled) == 1

    def test_companion_goal_completes_on_calm_recovery(self):
        analysis = _analysis(user_emotion={"emotion": "tired", "event": "daily"})
        _review(analysis=analysis)
        calm = CharacterState(mood="calm", intensity=0.3)
        changes = _review(character=calm, current_turn=11)
        assert len(changes.completed) == 1
        assert (
            changes.completed[0].description
            == goal_service.GOAL_DESCRIPTION_COMPANION
        )

    def test_companion_goal_stays_active_while_intensity_high(self):
        analysis = _analysis(user_emotion={"emotion": "tired", "event": "daily"})
        _review(analysis=analysis)
        calm_strong = CharacterState(mood="calm", intensity=0.6)
        changes = _review(character=calm_strong, current_turn=11)
        assert changes.completed == []

    def test_rest_goal_completes_after_five_turns(self):
        _review(executed_intention="suggest_rest", current_turn=3)
        changes = _review(executed_intention="suggest_rest", current_turn=7)
        assert changes.completed == []
        changes = _review(current_turn=8)
        assert len(changes.completed) == 1
        assert changes.completed[0].description == goal_service.GOAL_DESCRIPTION_REST


class TestExpiry:
    def test_goal_expires_past_ttl(self):
        analysis = _analysis(user_emotion={"emotion": "tired", "event": "daily"})
        _review(analysis=analysis, current_turn=3)
        changes = _review(current_turn=24)
        assert len(changes.expired) == 1
        assert changes.expired[0].status == "expired"

    def test_goal_stays_active_within_ttl(self):
        analysis = _analysis(user_emotion={"emotion": "tired", "event": "daily"})
        _review(analysis=analysis, current_turn=3)
        changes = _review(current_turn=23)
        assert changes.expired == []

    def test_persistent_goals_never_expire(self):
        _review(current_turn=3)
        _review(current_turn=200)
        persistent = [
            g
            for g in goal_repository.list_active(USER)
            if g.horizon == "persistent"
        ]
        assert len(persistent) == 3


class TestUserLanguageBoundary:
    def test_no_goal_created_without_policy_signals(self):
        changes = _review()
        assert changes.created == []
        assert goal_service.load_active(USER) == [] or all(
            g.source == "definition" for g in goal_repository.list_active(USER)
        )

    def test_created_goals_are_never_persistent(self):
        analysis = _analysis(
            user_emotion={"emotion": "tired", "event": "daily"},
            relationship_event={
                "type": "conflict",
                "magnitude": "strong",
                "confidence": 0.9,
            },
        )
        _review(
            analysis=analysis, executed_intention="suggest_rest", current_turn=3
        )
        _review(current_turn=4)
        rows = goal_repository.list_active(USER)
        current_rows = [g for g in rows if g.horizon == "current"]
        assert current_rows
        for goal in current_rows:
            assert goal.source in ("policy", "scene")
            assert goal.expires_at_turn is not None
            assert len(goal.description) <= GOAL_DESCRIPTION_MAX_LENGTH
        assert all(
            g.source == "definition" for g in rows if g.horizon == "persistent"
        )
