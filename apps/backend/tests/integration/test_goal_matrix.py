"""V6 testing.md 十四项必测矩阵（Case 1~13 聚合；Case 14 为全量回归命令本身）。"""

from datetime import datetime

import pytest

from app.models.character_state import CharacterState
from app.models.emotion import TurnAnalysis
from app.models.goal import GoalRecord
from app.models.intention import IntentionDecision
from app.models.relationship import RelationshipState
from app.models.scene import PendingAction, SceneState
from app.repositories import goal_repository
from app.services.goal import service as goal_service
from app.services.goal import intention as intention_policy

NOW = datetime(2026, 8, 29, 12, 0, 0)
DAY = datetime(2026, 8, 29, 12, 0, 0)
LATE_NIGHT = datetime(2026, 8, 29, 1, 0, 0)

USER = "u-matrix"
SESSION = "s-matrix"


def _analysis(emotion="neutral", event="daily", rel_type="none") -> TurnAnalysis:
    return TurnAnalysis(
        user_emotion={"emotion": emotion, "event": event},
        behavior={"behavior": "normal_reply", "reason": ""},
        emotion_event={"type": "none", "magnitude": "normal", "confidence": 0.0},
        relationship_event={"type": rel_type, "magnitude": "normal", "confidence": 0.9},
    )


def _scene(action: str | None = None, status: str = "pending") -> SceneState:
    pending = None
    if action is not None:
        pending = PendingAction(action=action, status=status, created_at_turn=1)
    return SceneState(session_id=SESSION, turn_id=1, pending_action=pending)


def _review(
    analysis=None,
    executed=None,
    turn=10,
    character=None,
    relationship=None,
    scene=None,
):
    return goal_service.review(
        USER,
        SESSION,
        analysis or _analysis(),
        executed,
        turn,
        character or CharacterState(),
        relationship or RelationshipState(),
        scene or _scene(),
    )


def _goal(goal_type, description, priority=3, offset=0, goal_id="") -> GoalRecord:
    return GoalRecord(
        id=goal_id or f"g-{goal_type}-{offset}",
        user_id=USER,
        type=goal_type,
        description=description,
        priority=priority,
        horizon="current",
        source="policy",
        created_turn=1,
        expires_at_turn=21,
        created_at=datetime.fromtimestamp(NOW.timestamp() + offset),
        updated_at=NOW,
    )


def _state(tension=0.0, intimacy=0.3, familiarity=0.3):
    return RelationshipState(
        tension=tension, intimacy=intimacy, familiarity=familiarity
    )


def _select(goals, **overrides):
    signals = {
        "tension": 0.0,
        "user_emotion": "neutral",
        "character_mood": "calm",
        "character_intensity": 0.3,
        "scene_pending": False,
        "late_night": False,
    }
    signals.update(overrides)
    return goal_service.select(goals, **signals)


def _conv_state(relationship: RelationshipState):
    from app.models.conversation import ConversationState

    return ConversationState(
        session_id=SESSION,
        user_id=USER,
        messages=[],
        summary=None,
        memories=[],
        current_input="x",
        relationship_state=relationship,
    )


@pytest.fixture(autouse=True)
def _db(db_session_factory):
    yield


class TestGoalLifecycle:
    def test_case_1_idempotent_seeding(self):
        _review(turn=1)
        _review(turn=2)
        persistent = [
            g for g in goal_repository.list_active(USER) if g.horizon == "persistent"
        ]
        assert len(persistent) == 3

    def test_case_2_conflict_event_creates_repair_goal(self):
        analysis = _analysis(rel_type="conflict")
        first = _review(analysis=analysis, relationship=RelationshipState(tension=0.6))
        second = _review(
            analysis=analysis, relationship=RelationshipState(tension=0.7), turn=11
        )
        assert [g.description for g in first.created] == [
            goal_service.GOAL_DESCRIPTION_REPAIR
        ]
        assert second.created == []

    def test_case_3_fatigue_creates_companion_goal(self):
        changes = _review(analysis=_analysis(emotion="tired"))
        assert [g.description for g in changes.created] == [
            goal_service.GOAL_DESCRIPTION_COMPANION
        ]

    def test_case_4_goal_completion(self):
        _review(
            analysis=_analysis(rel_type="boundary_violation"),
            relationship=RelationshipState(tension=0.6),
        )
        completed = _review(relationship=RelationshipState(tension=0.2), turn=11)
        assert [g.type for g in completed.completed] == ["relationship"]

        _review(analysis=_analysis(emotion="tired"), turn=12)
        recovered = _review(
            character=CharacterState(mood="calm", intensity=0.3), turn=13
        )
        assert any(
            g.description == goal_service.GOAL_DESCRIPTION_COMPANION
            for g in recovered.completed
        )

    def test_case_5_goal_expiry(self):
        _review(analysis=_analysis(emotion="sad"), turn=3)
        changes = _review(turn=24)
        assert any(g.status == "expired" for g in changes.expired)

    def test_case_6_user_language_never_creates_goals(self):
        for emotion in ("happy", "calm", "excited"):
            changes = _review(analysis=_analysis(emotion=emotion), turn=10)
            assert changes.created == []
        assert all(
            g.source == "definition"
            for g in goal_repository.list_active(USER)
        )


class TestSelectionAndConflict:
    def test_case_7_tier_order(self):
        goals = [
            _goal("scene", "完成切西瓜"),
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION),
            _goal("relationship", "维持日常亲近感"),
            _goal("conversation", "延续当前话题"),
        ]
        assert _select(goals, scene_pending=True).goal.type == "scene"
        without_scene = goals[1:]
        assert _select(without_scene).goal.type == "user_care"
        assert _select(without_scene[1:]).goal.type == "relationship"
        assert _select([without_scene[2]]).goal.type == "conversation"

    def test_case_8_context_corrections(self):
        goals = [
            _goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5),
            _goal("relationship", goal_service.GOAL_DESCRIPTION_REPAIR, priority=3),
        ]
        assert _select(goals, tension=0.6).goal.type == "relationship"

        rest = _goal("user_care", goal_service.GOAL_DESCRIPTION_REST, priority=4, offset=60)
        assert (
            _select(
                [goals[0], rest],
                user_emotion="tired",
                late_night=True,
            ).goal.description
            == goal_service.GOAL_DESCRIPTION_REST
        )

    def test_case_9_late_night_adjudication(self):
        companion = _goal(
            "user_care", goal_service.GOAL_DESCRIPTION_COMPANION, priority=5
        )
        rest = _goal(
            "user_care", goal_service.GOAL_DESCRIPTION_REST, priority=4, offset=60
        )
        selected = _select([companion, rest], user_emotion="tired", late_night=True)
        assert selected.goal.description == goal_service.GOAL_DESCRIPTION_REST
        assert companion.id in selected.suppressed
        assert "深夜" in selected.reason


class TestIntention:
    def test_case_10_same_goal_different_inputs(self):
        goal = goal_service.SelectedGoal(
            goal=_goal("user_care", goal_service.GOAL_DESCRIPTION_COMPANION),
            reason="疲惫",
        )
        comfort = intention_policy.enforce(
            IntentionDecision(intention="comfort_user", confidence=0.9),
            goal,
            _conv_state(_state()),
            _analysis(emotion="sad"),
            DAY,
        )
        assert comfort.intention == "comfort_user"

        rest = intention_policy.enforce(
            IntentionDecision(intention="suggest_rest", confidence=0.9),
            goal,
            _conv_state(_state()),
            _analysis(emotion="tired"),
            DAY,
        )
        assert rest.intention == "suggest_rest"

    def test_case_11_policy_validity_gates(self):
        goal = goal_service.SelectedGoal(
            goal=_goal("relationship", "维持日常亲近感"), reason="日常"
        )
        low_intimacy = intention_policy.enforce(
            IntentionDecision(intention="express_affection", confidence=0.9),
            goal,
            _conv_state(_state(intimacy=0.3)),
            _analysis(),
            DAY,
        )
        assert low_intimacy.degraded is True

        low_tension = intention_policy.enforce(
            IntentionDecision(intention="maintain_distance", confidence=0.9),
            goal,
            _conv_state(_state(tension=0.2)),
            _analysis(),
            DAY,
        )
        assert low_tension.degraded is True

        scene_goal = goal_service.SelectedGoal(
            goal=_goal("scene", "完成切西瓜"), reason="承诺"
        )
        during_pending = intention_policy.enforce(
            IntentionDecision(intention="share_own_feeling", confidence=0.9),
            scene_goal,
            _conv_state(_state()),
            _analysis(),
            DAY,
            scene_pending=True,
        )
        assert during_pending.intention == "continue_topic"
        assert during_pending.degraded is True

    def test_case_12_chain_failure_degrades(self):
        result = intention_policy.enforce(
            None,
            None,
            _conv_state(_state()),
            _analysis(),
            DAY,
        )
        assert result.intention == "continue_topic"
        assert result.degraded is True
