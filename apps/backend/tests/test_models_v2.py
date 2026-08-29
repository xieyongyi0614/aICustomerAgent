import pytest
from pydantic import ValidationError

from app.models.behavior import BehaviorDecision
from app.models.character_state import CharacterState, StateUpdateDecision
from app.models.conversation import ConversationState
from app.models.emotion import TurnAnalysis, UserEmotion
from app.models.relationship import RelationshipState


class TestCharacterState:
    def test_default_state(self):
        state = CharacterState()
        assert state.mood == "calm"
        assert state.energy == 0.9
        assert state.current_topic == ""
        assert state.updated_at is None

    @pytest.mark.parametrize("energy", [-0.1, 1.5])
    def test_energy_out_of_range_rejected(self, energy):
        with pytest.raises(ValidationError):
            CharacterState(energy=energy)

    def test_invalid_mood_rejected(self):
        with pytest.raises(ValidationError):
            CharacterState(mood="grumpy")

    def test_state_update_decision_defaults_after_v5_mood_retirement(self):
        decision = StateUpdateDecision()
        assert decision.mood == "calm"
        assert decision.inner_state == ""
        assert decision.current_topic == ""


class TestRelationshipState:
    def test_default_state(self):
        relationship = RelationshipState()
        assert relationship.intimacy == 0.3
        assert relationship.trust == 0.35
        assert relationship.familiarity == 0.3
        assert relationship.stage == "friend"

    @pytest.mark.parametrize(
        "field", ["intimacy", "trust", "familiarity"]
    )
    def test_dimensions_out_of_range_rejected(self, field):
        with pytest.raises(ValidationError):
            RelationshipState(**{field: 1.5})

    def test_invalid_stage_rejected(self):
        with pytest.raises(ValidationError):
            RelationshipState(stage="enemy")


class TestTurnAnalysis:
    def test_default_is_degradation_snapshot(self):
        analysis = TurnAnalysis()
        assert analysis.user_emotion.emotion == "neutral"
        assert analysis.user_emotion.event == "daily"
        assert analysis.behavior.behavior == "normal_reply"
        assert analysis.behavior.reason == ""

    def test_nested_validation_rejects_unknown_event(self):
        with pytest.raises(ValidationError):
            TurnAnalysis(user_emotion=UserEmotion(event="party"))

    def test_full_construction(self):
        analysis = TurnAnalysis.model_validate(
            {
                "user_emotion": {"emotion": "happy", "event": "achievement"},
                "behavior": {"behavior": "celebrate", "reason": "用户达成成就"},
            }
        )
        assert analysis.behavior.behavior == "celebrate"


class TestConversationStateCompat:
    def test_new_fields_have_defaults(self):
        state = ConversationState(
            session_id="s",
            user_id="u",
            messages=[],
            summary=None,
            memories=[],
            current_input="hi",
        )
        assert state.character_state.mood == "calm"
        assert state.relationship_state.stage == "friend"

    def test_invalid_behavior_rejected(self):
        with pytest.raises(ValidationError):
            BehaviorDecision(behavior="dance")
