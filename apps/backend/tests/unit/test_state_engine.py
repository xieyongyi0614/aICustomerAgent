from datetime import datetime, timedelta

import pytest

from app.models.character_state import CharacterState, StateUpdateDecision
from app.models.emotion import TurnAnalysis, UserEmotion
from app.models.behavior import BehaviorDecision
from app.services import state_engine


def _analysis(event, behavior="normal_reply", emotion="neutral"):
    return TurnAnalysis(
        user_emotion=UserEmotion(emotion=emotion, event=event),
        behavior=BehaviorDecision(behavior=behavior),
    )


class TestUpdateEnergy:
    def test_daily_turn_decays_energy(self):
        state = CharacterState(energy=0.9)
        assert state_engine.update_energy(state, _analysis("daily")) == pytest.approx(0.85)

    def test_achievement_offsets_decay_and_caps_at_one(self):
        state = CharacterState(energy=0.98)
        assert state_engine.update_energy(state, _analysis("achievement")) == 1.0

    def test_conflict_and_comfort_drain_but_floor_at_energy_min(self):
        state = CharacterState(energy=0.2)
        energy = state_engine.update_energy(
            state, _analysis("conflict", behavior="comfort")
        )
        assert energy == pytest.approx(0.1)

    def test_unknown_event_has_no_modifier(self):
        state = CharacterState(energy=0.5)
        assert state_engine.update_energy(state, _analysis("farewell")) == pytest.approx(0.45)

    @pytest.mark.parametrize(
        "event,behavior,expected",
        [
            ("help_given", "normal_reply", 0.5),
            ("setback", "normal_reply", 0.4),
            ("complaint", "normal_reply", 0.4),
            ("daily", "show_concern", 0.42),
        ],
    )
    def test_event_and_behavior_energy_modifiers(self, event, behavior, expected):
        state = CharacterState(energy=0.5)
        energy = state_engine.update_energy(state, _analysis(event, behavior=behavior))
        assert energy == pytest.approx(expected)


class TestRelationshipDeltas:
    def test_achievement_plus_recall_memory_stacks(self):
        delta = state_engine.relationship_deltas("achievement", "recall_memory")
        assert delta.intimacy == pytest.approx(0.04)
        assert delta.trust == pytest.approx(0.02)
        assert delta.familiarity == pytest.approx(0.05)

    def test_share_goal_plus_recall_memory_stacks(self):
        delta = state_engine.relationship_deltas("share_goal", "recall_memory")
        assert delta.intimacy == pytest.approx(0.02)
        assert delta.trust == pytest.approx(0.08)
        assert delta.familiarity == pytest.approx(0.03)

    @pytest.mark.parametrize(
        "event,behavior,intimacy,trust,familiarity",
        [
            ("setback", "normal_reply", 0.03, 0.0, 0.0),
            ("seek_help", "normal_reply", 0.02, 0.05, 0.02),
            ("help_given", "normal_reply", 0.03, 0.02, 0.06),
            ("complaint", "normal_reply", 0.0, -0.03, 0.0),
            ("daily", "celebrate", 0.02, 0.0, 0.01),
            ("daily", "encourage", 0.0, 0.01, 0.01),
        ],
    )
    def test_delta_table_entry(self, event, behavior, intimacy, trust, familiarity):
        delta = state_engine.relationship_deltas(event, behavior)
        assert delta.intimacy == pytest.approx(intimacy)
        assert delta.trust == pytest.approx(trust)
        assert delta.familiarity == pytest.approx(familiarity)

    def test_conflict_applies_full_negative_delta(self):
        relationship = state_engine.apply_relationship(
            _relationship(intimacy=0.5, trust=0.5, familiarity=0.5),
            "conflict",
            "normal_reply",
        )
        assert relationship.intimacy == pytest.approx(0.38)
        assert relationship.trust == pytest.approx(0.40)
        assert relationship.familiarity == pytest.approx(0.45)

    def test_delta_clamps_at_zero(self):
        relationship = state_engine.apply_relationship(
            _relationship(intimacy=0.0, trust=0.0, familiarity=0.0),
            "conflict",
            "normal_reply",
        )
        assert relationship.intimacy == 0.0
        assert relationship.trust == 0.0

    def test_delta_clamps_at_one(self):
        relationship = state_engine.apply_relationship(
            _relationship(intimacy=0.99, trust=0.99, familiarity=0.99, stage="partner"),
            "help_given",
            "recall_memory",
        )
        assert relationship.intimacy == 1.0
        assert relationship.trust == 1.0
        assert relationship.familiarity == 1.0
        assert relationship.stage == "partner"


def _relationship(intimacy, trust, familiarity, stage="friend"):
    from app.models.relationship import RelationshipState

    return RelationshipState(
        intimacy=intimacy, trust=trust, familiarity=familiarity, stage=stage
    )


class TestNextStage:
    def test_stranger_upgrades_to_friend_on_familiarity(self):
        assert state_engine.next_stage(0.1, 0.1, 0.35, "stranger") == "friend"

    def test_friend_upgrades_to_close_friend(self):
        assert state_engine.next_stage(0.55, 0.55, 0.4, "friend") == "close_friend"

    def test_close_friend_upgrades_to_partner(self):
        assert state_engine.next_stage(0.75, 0.75, 0.6, "close_friend") == "partner"

    def test_partial_requirements_do_not_upgrade(self):
        assert state_engine.next_stage(0.6, 0.5, 0.4, "friend") == "friend"

    def test_drop_inside_hysteresis_band_keeps_stage(self):
        assert state_engine.next_stage(0.5, 0.5, 0.4, "close_friend") == "close_friend"

    def test_drop_below_hysteresis_line_demotes_one_stage(self):
        assert state_engine.next_stage(0.44, 0.44, 0.4, "close_friend") == "friend"

    def test_partner_demotes_below_line(self):
        assert state_engine.next_stage(0.6, 0.6, 0.6, "partner") == "close_friend"


class TestApplyIdleRecovery:
    def test_recent_state_unchanged(self):
        now = datetime.now()
        state = CharacterState(energy=0.3, mood="tired", updated_at=now - timedelta(hours=1))
        recovered = state_engine.apply_idle_recovery(state, now)
        assert recovered.energy == pytest.approx(0.3)
        assert recovered.mood == "tired"

    def test_idle_over_reset_hours_restores_energy_and_mood(self):
        now = datetime.now()
        state = CharacterState(energy=0.3, mood="tired", updated_at=now - timedelta(hours=13))
        recovered = state_engine.apply_idle_recovery(state, now)
        assert recovered.energy == pytest.approx(0.85)
        assert recovered.mood == "calm"

    def test_recovery_never_lowers_high_energy(self):
        now = datetime.now()
        state = CharacterState(energy=0.95, mood="calm", updated_at=now - timedelta(hours=48))
        recovered = state_engine.apply_idle_recovery(state, now)
        assert recovered.energy == pytest.approx(0.95)

    def test_no_updated_at_skips_recovery(self):
        state = CharacterState(energy=0.2, mood="tired", updated_at=None)
        assert state_engine.apply_idle_recovery(state, datetime.now()) == state


class TestApplyCharacter:
    def test_decision_ignores_mood_and_updates_inner_state_topic(self):
        now = datetime.now()
        decision = StateUpdateDecision(
            mood="worried",
            mood_reason="用户连续熬夜",
            inner_state="担心用户过度疲劳",
            current_topic="用户的 AI Agent 项目",
        )
        result = state_engine.apply_character(
            CharacterState(energy=0.9, mood="calm"), decision, _analysis("daily"), now
        )
        assert result.mood == "calm"
        assert result.inner_state == "担心用户过度疲劳"
        assert result.current_topic == "用户的 AI Agent 项目"
        assert result.energy == pytest.approx(0.85)
        assert result.updated_at == now

    def test_none_decision_keeps_mood_and_topic_but_updates_energy(self):
        now = datetime.now()
        result = state_engine.apply_character(
            CharacterState(energy=0.9, mood="happy", current_topic="旅行", inner_state="开心"),
            None,
            _analysis("daily"),
            now,
        )
        assert result.mood == "happy"
        assert result.current_topic == "旅行"
        assert result.inner_state == "开心"
        assert result.energy == pytest.approx(0.85)
        assert result.updated_at == now
