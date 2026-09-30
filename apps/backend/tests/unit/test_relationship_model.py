from datetime import datetime, timedelta

import pytest

from app.core.constants import (
    MAGNITUDE_COEFFICIENTS,
    RELATIONSHIP_EVENT_DELTAS,
    BEHAVIOR_DELTAS,
)
from app.models.relationship import (
    ConflictRecord,
    InteractionSignal,
    MilestoneRecord,
    RelationshipDelta,
    RelationshipState,
)
from app.engines import relationship_evolution
from app.engines import state as state_engine


NOW = datetime(2026, 8, 31, 12, 0, 0)

SIX_DIMENSIONS = ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")

EVENT_TYPES = (
    "user_care",
    "user_help",
    "long_interaction",
    "intimate_moment",
    "praise",
    "warm_moment",
    "criticized",
    "conflict",
    "boundary_violation",
    "promise_kept",
    "promise_broken",
    "none",
)


def make_state(**overrides):
    payload = {
        "intimacy": 0.3,
        "trust": 0.35,
        "familiarity": 0.3,
        "respect": 0.6,
        "comfort": 0.6,
        "tension": 0.0,
        "stage": "friend",
    }
    payload.update(overrides)
    return RelationshipState(**payload)


class TestDimensionDefaults:
    def test_default_state_has_five_plus_one_dimensions(self):
        state = RelationshipState()
        assert state.intimacy == pytest.approx(0.30)
        assert state.trust == pytest.approx(0.35)
        assert state.familiarity == pytest.approx(0.30)
        assert state.respect == pytest.approx(0.60)
        assert state.comfort == pytest.approx(0.60)
        assert state.tension == pytest.approx(0.0)
        assert state.stage == "friend"
        assert state.conflict_status == "none"
        assert state.neglect_active is False
        assert state.last_interaction_at is None
        assert state.version == 0

    def test_new_dimensions_clamped_to_unit_range(self):
        with pytest.raises(ValueError):
            RelationshipState(respect=1.5)
        with pytest.raises(ValueError):
            RelationshipState(comfort=-0.1)

    def test_delta_table_covers_all_event_types_six_columns(self):
        for event_type in EVENT_TYPES:
            delta = RELATIONSHIP_EVENT_DELTAS[event_type]
            for dim in SIX_DIMENSIONS:
                assert isinstance(getattr(delta, dim), float)
        assert RELATIONSHIP_EVENT_DELTAS["none"] == RelationshipDelta()

    def test_promise_rows_values(self):
        kept = RELATIONSHIP_EVENT_DELTAS["promise_kept"]
        assert kept.trust == pytest.approx(0.05)
        assert kept.respect == pytest.approx(0.02)
        broken = RELATIONSHIP_EVENT_DELTAS["promise_broken"]
        assert broken.trust == pytest.approx(-0.12)
        assert broken.respect == pytest.approx(-0.08)

    def test_behavior_deltas_carry_comfort(self):
        for behavior, comfort in (
            ("comfort", 0.02),
            ("celebrate", 0.02),
            ("encourage", 0.01),
            ("recall_memory", 0.01),
        ):
            assert BEHAVIOR_DELTAS[behavior].comfort == pytest.approx(comfort)

    def test_impact_builder_links_magnitude_for_six_dimensions(self):
        impact = state_engine.build_relationship_impact("conflict", "strong")
        base = RELATIONSHIP_EVENT_DELTAS["conflict"]
        coefficient = MAGNITUDE_COEFFICIENTS["strong"]
        for dim in SIX_DIMENSIONS:
            assert getattr(impact, dim) == pytest.approx(
                round(getattr(base, dim) * coefficient, 6)
            )


class TestStageInsensitiveToNewDimensions:
    def test_stage_path_ignores_respect_and_comfort(self):
        state = make_state(intimacy=0.60, trust=0.60, familiarity=0.40)
        baseline = state_engine.apply_relationship_v5(
            state, "none", "normal", "normal_reply", RelationshipDelta(), RelationshipDelta()
        )
        extremes = make_state(
            intimacy=0.60,
            trust=0.60,
            familiarity=0.40,
            respect=1.0,
            comfort=0.0,
        )
        padded = state_engine.apply_relationship_v5(
            extremes, "none", "normal", "normal_reply", RelationshipDelta(), RelationshipDelta()
        )
        assert baseline[0].stage == padded[0].stage == "close_friend"
        assert baseline[0].respect == pytest.approx(0.60)
        assert padded[0].respect == pytest.approx(1.0)
        assert padded[0].comfort == pytest.approx(0.0)

    def test_v5_state_update_never_moves_new_dimensions(self):
        state = make_state()
        new, applied = state_engine.apply_relationship_v5(
            state, "user_care", "normal", "comfort", RelationshipDelta(), RelationshipDelta()
        )
        assert applied.respect == pytest.approx(0.0)
        assert applied.comfort == pytest.approx(0.0)
        assert new.respect == pytest.approx(0.6)
        assert new.comfort == pytest.approx(0.6)


class TestComfortBaseline:
    def test_baseline_per_stage(self):
        assert relationship_evolution.comfort_baseline("stranger") == pytest.approx(0.45)
        assert relationship_evolution.comfort_baseline("friend") == pytest.approx(0.60)
        assert relationship_evolution.comfort_baseline("close_friend") == pytest.approx(0.70)
        assert relationship_evolution.comfort_baseline("partner") == pytest.approx(0.80)

    def test_conflict_penalizes_baseline(self):
        assert relationship_evolution.comfort_baseline(
            "friend", conflict_active=True
        ) == pytest.approx(0.50)

    def test_baseline_stays_in_unit_range(self):
        assert 0.0 <= relationship_evolution.comfort_baseline("partner", True) <= 1.0


class TestDistanceIndex:
    def test_zero_when_intimate_and_recent(self):
        state = make_state(tension=0.0, comfort=1.0)
        state = state.model_copy(update={"last_interaction_at": NOW})
        assert relationship_evolution.distance_index(state, NOW) == pytest.approx(0.0)

    def test_one_when_all_adverse(self):
        state = make_state(tension=1.0, comfort=0.0, stage="stranger")
        state = state.model_copy(update={"last_interaction_at": NOW - timedelta(days=30)})
        assert relationship_evolution.distance_index(state, NOW) == pytest.approx(1.0)

    def test_no_interaction_record_caps_recency_penalty(self):
        state = make_state(tension=0.0, comfort=1.0)
        assert relationship_evolution.distance_index(state, NOW) == pytest.approx(0.2)

    def test_recency_penalty_scales_with_gap(self):
        state = make_state(tension=0.0, comfort=1.0, stage="partner")
        state = state.model_copy(update={"last_interaction_at": NOW - timedelta(days=1)})
        assert relationship_evolution.distance_index(state, NOW) == pytest.approx(0.1)


class TestTierTexts:
    def test_respect_tiers(self):
        from app.character.asuna.relationship_lexicon import describe_respect

        assert describe_respect(0.2) == "言行让你有些失望"
        assert describe_respect(0.6) == "保持应有的尊重"
        assert describe_respect(0.9) == "由衷敬佩"

    def test_comfort_tiers(self):
        from app.character.asuna.relationship_lexicon import describe_comfort

        assert describe_comfort(0.2) == "相处有些放不开"
        assert describe_comfort(0.6) == "相处还算自在"
        assert describe_comfort(0.9) == "相处毫无负担"


class TestNewModels:
    def test_interaction_signal_defaults(self):
        signal = InteractionSignal(kind="gratitude", quality="positive", salience=0.5)
        assert signal.novelty == pytest.approx(1.0)
        assert signal.cause == ""

    def test_milestone_record_defaults(self):
        record = MilestoneRecord(
            user_id="u1",
            milestone_key="first_self_disclosure",
            created_at=NOW,
        )
        assert record.applied_bonus == RelationshipDelta()
        assert record.unlocks == ()
        assert record.period_key == ""

    def test_conflict_record_defaults(self):
        record = ConflictRecord(
            user_id="u1", status="conflict", started_at=NOW, created_at=NOW
        )
        assert record.resolution == ""
        assert record.resolved_at is None
