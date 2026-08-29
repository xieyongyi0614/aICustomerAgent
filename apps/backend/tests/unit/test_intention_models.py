from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.intention import (
    EXPRESSION_INTENTIONS,
    INTENTION_BEHAVIOR_MAP,
    INTENTION_GOAL_DEFAULTS,
    INTENTION_GOAL_FIT,
    INTENTION_REASON_MAX_LENGTH,
    IntentionDecision,
    IntentionType,
    ValidatedIntention,
)

ALL_INTENTIONS = [
    "comfort_user",
    "suggest_rest",
    "encourage_user",
    "celebrate_with_user",
    "express_affection",
    "tease_user",
    "maintain_distance",
    "repair_rapport",
    "continue_topic",
    "ask_followup",
    "share_own_feeling",
    "lighten_mood",
]


class TestIntentionDecision:
    def test_all_twelve_values_accepted(self):
        for intention in ALL_INTENTIONS:
            decision = IntentionDecision(intention=intention, confidence=0.8)
            assert decision.intention == intention

    def test_invalid_intention_rejected(self):
        with pytest.raises(ValidationError):
            IntentionDecision(intention="end_conversation", confidence=0.5)

    @pytest.mark.parametrize("confidence", [-0.1, 1.1])
    def test_confidence_bounds_enforced(self, confidence):
        with pytest.raises(ValidationError):
            IntentionDecision(intention="continue_topic", confidence=confidence)

    def test_reason_over_limit_rejected(self):
        with pytest.raises(ValidationError):
            IntentionDecision(
                intention="continue_topic", reason="长" * (INTENTION_REASON_MAX_LENGTH + 1)
            )

    def test_reason_within_limit_accepted(self):
        decision = IntentionDecision(
            intention="comfort_user", reason="用户表达疲惫，选择安抚"
        )
        assert decision.confidence == 0.5


class TestValidatedIntention:
    def test_defaults(self):
        validated = ValidatedIntention(intention="continue_topic")
        assert validated.degraded is False
        assert validated.goal_id is None
        assert validated.reason == ""


class TestTables:
    def test_goal_fit_covers_all_intentions(self):
        assert set(INTENTION_GOAL_FIT) == set(ALL_INTENTIONS)

    def test_goal_fit_values_are_goal_types(self):
        for fits in INTENTION_GOAL_FIT.values():
            assert fits <= {"user_care", "relationship", "conversation", "scene"}

    def test_defaults_cover_all_goal_types(self):
        assert set(INTENTION_GOAL_DEFAULTS) == {
            "user_care",
            "relationship",
            "conversation",
            "scene",
        }
        for default in INTENTION_GOAL_DEFAULTS.values():
            assert default in ALL_INTENTIONS

    def test_expression_intentions_subset(self):
        assert EXPRESSION_INTENTIONS <= set(ALL_INTENTIONS)

    def test_behavior_map_values_are_v2_behaviors(self):
        assert set(INTENTION_BEHAVIOR_MAP.values()) <= {
            "comfort",
            "show_concern",
            "encourage",
            "celebrate",
            "ask_followup",
        }
