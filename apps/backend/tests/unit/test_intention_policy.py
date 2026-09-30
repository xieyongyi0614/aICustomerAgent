from datetime import datetime

import pytest

from app.models.character_state import CharacterState
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis
from app.models.intention import IntentionDecision
from app.models.relationship import RelationshipState
from app.services.goal import intention as intention_policy
from app.services.goal.service import (
    GOAL_DESCRIPTION_COMPANION,
    GOAL_DESCRIPTION_REPAIR,
    SelectedGoal,
)
from app.models.goal import GoalRecord

DAY = datetime(2026, 8, 29, 12, 0, 0)
LATE_NIGHT = datetime(2026, 8, 29, 1, 0, 0)

NOW_TS = datetime(2026, 8, 29, 12, 0, 0).timestamp()


def _goal(goal_type: str, description: str, goal_id: str = "g-1") -> GoalRecord:
    from datetime import datetime as dt

    return GoalRecord(
        id=goal_id,
        user_id="u1",
        type=goal_type,
        description=description,
        priority=5,
        horizon="current",
        source="policy",
        created_turn=1,
        expires_at_turn=21,
        created_at=dt.fromtimestamp(NOW_TS),
        updated_at=dt.fromtimestamp(NOW_TS),
    )


def _selected(goal_type: str, description: str, goal_id: str = "g-1") -> SelectedGoal:
    return SelectedGoal(goal=_goal(goal_type, description, goal_id), reason="测试")


def _state(
    intimacy=0.3, trust=0.35, familiarity=0.3, tension=0.0
) -> ConversationState:
    return ConversationState(
        session_id="s1",
        user_id="u1",
        messages=[],
        summary=None,
        memories=[],
        current_input="在吗",
        relationship_state=RelationshipState(
            intimacy=intimacy, trust=trust, familiarity=familiarity, tension=tension
        ),
    )


def _analysis(emotion="neutral", event="daily", emotion_event_type="none") -> TurnAnalysis:
    return TurnAnalysis(
        user_emotion={"emotion": emotion, "event": event},
        emotion_event={
            "type": emotion_event_type,
            "magnitude": "normal",
            "confidence": 0.9,
        },
    )


def _enforce(
    decision,
    goal_type="conversation",
    description="延续当前话题",
    state=None,
    analysis=None,
    now=DAY,
    scene_pending=False,
    goal_id="g-1",
):
    return intention_policy.enforce(
        decision,
        _selected(goal_type, description, goal_id),
        state or _state(),
        analysis,
        now,
        scene_pending=scene_pending,
    )


class TestDegradation:
    def test_none_decision_degrades_to_continue_topic(self):
        result = _enforce(None)
        assert result.intention == "continue_topic"
        assert result.degraded is True
        assert result.goal_id == "g-1"
        assert result.reason == intention_policy._DEGRADED_REASON

    def test_non_decision_object_degrades(self):
        result = _enforce({"intention": "comfort_user"})
        assert result.intention == "continue_topic"
        assert result.degraded is True


class TestValidityRules:
    def test_express_affection_requires_intimacy(self):
        decision = IntentionDecision(intention="express_affection", confidence=0.9)
        close = _state(intimacy=0.6)
        ok = _enforce(decision, "relationship", "维持亲近感", state=close)
        assert ok.intention == "express_affection"
        assert ok.degraded is False

        distant = _state(intimacy=0.4)
        degraded = _enforce(decision, "relationship", "维持亲近感", state=distant)
        assert degraded.intention == "continue_topic"
        assert degraded.degraded is True

    def test_tease_user_requires_familiarity_and_low_tension(self):
        decision = IntentionDecision(intention="tease_user", confidence=0.9)
        ok = _enforce(decision, state=_state(familiarity=0.5, tension=0.2))
        assert ok.intention == "tease_user"

        low_familiarity = _enforce(decision, state=_state(familiarity=0.2, tension=0.1))
        assert low_familiarity.degraded is True

        tense = _enforce(decision, state=_state(familiarity=0.5, tension=0.5))
        assert tense.degraded is True

    def test_maintain_distance_only_when_tension_high(self):
        decision = IntentionDecision(intention="maintain_distance", confidence=0.9)
        ok = _enforce(
            decision, "relationship", "维持亲近感", state=_state(tension=0.6)
        )
        assert ok.intention == "maintain_distance"

        calm = _enforce(
            decision, "relationship", "维持亲近感", state=_state(tension=0.3)
        )
        assert calm.degraded is True

    def test_repair_rapport_requires_tension(self):
        decision = IntentionDecision(intention="repair_rapport", confidence=0.9)
        ok = _enforce(
            decision, "relationship", GOAL_DESCRIPTION_REPAIR, state=_state(tension=0.4)
        )
        assert ok.intention == "repair_rapport"

        calm = _enforce(
            decision, "relationship", GOAL_DESCRIPTION_REPAIR, state=_state(tension=0.1)
        )
        assert calm.degraded is True

    def test_celebrate_requires_achievement_or_happy(self):
        decision = IntentionDecision(intention="celebrate_with_user", confidence=0.9)
        ok = _enforce(decision, analysis=_analysis(emotion="happy"))
        assert ok.intention == "celebrate_with_user"

        ok_achievement = _enforce(decision, analysis=_analysis(event="achievement"))
        assert ok_achievement.intention == "celebrate_with_user"

        neutral = _enforce(decision, analysis=_analysis())
        assert neutral.degraded is True

    def test_suggest_rest_requires_tired_or_late_night(self):
        decision = IntentionDecision(intention="suggest_rest", confidence=0.9)
        ok_tired = _enforce(
            decision, "user_care", "劝用户早点休息", analysis=_analysis(emotion="tired")
        )
        assert ok_tired.intention == "suggest_rest"

        ok_late = _enforce(decision, "user_care", "劝用户早点休息", now=LATE_NIGHT)
        assert ok_late.intention == "suggest_rest"

        day_calm = _enforce(
            decision, "user_care", "劝用户早点休息", analysis=_analysis(emotion="calm")
        )
        assert day_calm.degraded is True

    def test_comfort_user_requires_negative_signal(self):
        decision = IntentionDecision(intention="comfort_user", confidence=0.9)
        ok_sad = _enforce(
            decision, "user_care", "陪伴用户放松", analysis=_analysis(emotion="sad")
        )
        assert ok_sad.intention == "comfort_user"

        ok_event = _enforce(
            decision,
            "user_care",
            "陪伴用户放松",
            analysis=_analysis(emotion_event_type="criticized"),
        )
        assert ok_event.intention == "comfort_user"

        happy = _enforce(
            decision, "user_care", "陪伴用户放松", analysis=_analysis(emotion="happy")
        )
        assert happy.degraded is True

    def test_always_valid_intentions_pass(self):
        for intention in ("continue_topic", "ask_followup", "lighten_mood"):
            decision = IntentionDecision(intention=intention, confidence=0.7)
            result = _enforce(decision)
            assert result.intention == intention
            assert result.degraded is False


class TestGoalConsistency:
    def test_express_affection_under_user_care_goal_degrades_to_comfort(self):
        decision = IntentionDecision(intention="express_affection", confidence=0.9)
        result = _enforce(
            decision,
            goal_type="user_care",
            description="陪伴用户放松",
            state=_state(intimacy=0.7),
            analysis=_analysis(emotion="sad"),
        )
        assert result.intention == "comfort_user"
        assert result.degraded is True
        assert result.goal_id == "g-1"

    def test_degraded_default_itself_invalid_falls_back_to_continue_topic(self):
        decision = IntentionDecision(intention="celebrate_with_user", confidence=0.9)
        result = _enforce(
            decision,
            goal_type="user_care",
            description="陪伴用户放松",
            analysis=_analysis(emotion="happy"),
        )
        assert result.intention == "continue_topic"
        assert result.degraded is True

    def test_validity_checked_before_goal_consistency(self):
        decision = IntentionDecision(intention="celebrate_with_user", confidence=0.9)
        result = _enforce(
            decision,
            goal_type="user_care",
            description="陪伴用户放松",
            analysis=_analysis(emotion="sad"),
        )
        assert result.intention == "continue_topic"
        assert result.degraded is True

    def test_fitting_intention_keeps_llm_reason(self):
        decision = IntentionDecision(
            intention="ask_followup",
            confidence=0.8,
            reason="想多了解用户近况",
        )
        result = _enforce(decision, goal_type="conversation", description="延续当前话题")
        assert result.intention == "ask_followup"
        assert result.degraded is False
        assert result.reason == "想多了解用户近况"


class TestScenePriority:
    def test_expression_intention_yields_to_pending_action(self):
        decision = IntentionDecision(intention="express_affection", confidence=0.9)
        result = _enforce(
            decision,
            "relationship",
            "维持亲近感",
            state=_state(intimacy=0.7),
            scene_pending=True,
        )
        assert result.intention == "continue_topic"
        assert result.degraded is True
        assert "场景承诺" in result.reason

    def test_non_expression_intention_unaffected_by_pending(self):
        decision = IntentionDecision(intention="ask_followup", confidence=0.9)
        result = _enforce(decision, scene_pending=True)
        assert result.intention == "ask_followup"
        assert result.degraded is False


class TestReasonTruncation:
    def test_overlong_reason_truncated_by_policy(self):
        decision = IntentionDecision.model_construct(
            intention="continue_topic", confidence=0.7, reason="长" * 200
        )
        result = _enforce(decision)
        assert len(result.reason) == intention_policy.INTENTION_REASON_MAX_LENGTH
        assert result.degraded is False
