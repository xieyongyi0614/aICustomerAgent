from datetime import datetime

import pytest

from app.models.relationship import RelationshipDelta, RelationshipState
from app.engines import state as state_engine


def make_state(**overrides):
    payload = {
        "intimacy": 0.3,
        "trust": 0.35,
        "familiarity": 0.3,
        "tension": 0.0,
        "stage": "friend",
    }
    payload.update(overrides)
    return RelationshipState(**payload)


ZERO_DAY = RelationshipDelta()
TODAY = datetime(2026, 8, 29, 12, 0, 0)


def apply(state, event_type, magnitude="normal", behavior="normal_reply",
          day_positive=None, day_negative=None):
    return state_engine.apply_relationship_update(
        state,
        event_type,
        magnitude,
        behavior,
        day_positive or RelationshipDelta(),
        day_negative or RelationshipDelta(),
    )


class TestLayeredCaps:
    def test_strong_conflict_capped_by_turn_limit(self):
        state = make_state()
        new, applied = apply(state, "conflict", magnitude="strong")
        for dim in ("intimacy", "trust", "familiarity", "tension"):
            assert abs(getattr(applied, dim)) <= 0.15 + 1e-9
        assert applied.intimacy == pytest.approx(-0.15)
        assert applied.tension == pytest.approx(0.15)

    def test_builder_returns_raw_scaled_delta(self):
        impact = state_engine.build_relationship_impact("conflict", "strong")
        assert impact.tension == pytest.approx(0.20 * 1.4)
        assert impact.intimacy == pytest.approx(-0.12 * 1.4)

    def test_event_component_capped_in_updater(self):
        _, applied = apply(make_state(), "conflict", magnitude="strong")
        for dim in ("intimacy", "trust", "familiarity", "tension"):
            assert abs(getattr(applied, dim)) <= 0.15 + 1e-9

    def test_event_plus_behavior_combined_capped(self):
        state = make_state()
        new, applied = apply(state, "user_care", behavior="comfort")
        assert abs(applied.intimacy) <= 0.15
        assert abs(applied.trust) <= 0.15

    def test_values_stay_in_unit_range(self):
        state = make_state(tension=0.95)
        new, _ = apply(state, "conflict", magnitude="strong")
        assert 0.0 <= new.tension <= 1.0
        new2, _ = apply(make_state(trust=0.02), "conflict", magnitude="strong")
        assert new2.trust >= 0.0


class TestDayCap:
    def test_positive_day_cap_truncates(self):
        state = make_state(trust=0.5)
        day_positive = RelationshipDelta(trust=0.28)
        new, applied = apply(
            state, "user_care", day_positive=day_positive
        )
        assert applied.trust == pytest.approx(0.02)

    def test_day_cap_exhausted_blocks_further_positive(self):
        state = make_state(trust=0.5)
        day_positive = RelationshipDelta(trust=0.30)
        new, applied = apply(state, "user_care", day_positive=day_positive)
        assert applied.trust == pytest.approx(0.0)
        assert new.trust == 0.5

    def test_negative_day_cap_independent(self):
        state = make_state(trust=0.5)
        day_positive = RelationshipDelta(trust=0.30)
        new, applied = apply(state, "conflict", magnitude="strong", day_positive=day_positive)
        assert applied.trust == pytest.approx(-0.14)

    def test_day_cap_applies_to_tension_too(self):
        state = make_state(tension=0.0)
        day_negative = RelationshipDelta(tension=0.28)
        new, applied = apply(
            state, "conflict", magnitude="strong", day_negative=day_negative
        )
        assert applied.tension == pytest.approx(0.02)


class TestTensionRules:
    def test_positive_interaction_consumes_tension(self):
        state = make_state(tension=0.4)
        new, applied = apply(state, "user_care")
        assert applied.tension == pytest.approx(-0.02)
        assert new.tension == pytest.approx(0.38)

    def test_tension_never_negative(self):
        state = make_state(tension=0.01)
        new, _ = apply(state, "user_care", magnitude="strong")
        assert new.tension >= 0.0


class TestStageFreeze:
    def test_upgrade_frozen_when_tension_above_0_5(self):
        state = make_state(
            intimacy=0.60, trust=0.60, familiarity=0.40, tension=0.55, stage="friend"
        )
        new, _ = apply(state, "none")
        assert new.stage == "friend"

    def test_upgrade_allowed_when_tension_below_freeze(self):
        state = make_state(
            intimacy=0.60, trust=0.60, familiarity=0.40, tension=0.40, stage="friend"
        )
        new, _ = apply(state, "none")
        assert new.stage == "close_friend"

    def test_downgrade_not_blocked_by_freeze(self):
        state = make_state(
            intimacy=0.20, trust=0.20, familiarity=0.20, tension=0.60,
            stage="friend",
        )
        new, _ = apply(state, "none")
        assert new.stage == "stranger"


class TestAccounting:
    def test_impact_sum_matches_state_change(self):
        state = make_state()
        new, applied = apply(state, "user_care")
        assert new.intimacy == pytest.approx(state.intimacy + applied.intimacy, abs=1e-9)
        assert new.trust == pytest.approx(state.trust + applied.trust, abs=1e-9)
        assert new.familiarity == pytest.approx(state.familiarity + applied.familiarity, abs=1e-9)
        assert new.tension == pytest.approx(state.tension + applied.tension, abs=1e-9)

    def test_truncated_impact_recorded_as_actual(self):
        state = make_state(trust=0.5)
        day_positive = RelationshipDelta(trust=0.29)
        _, applied = apply(state, "user_care", day_positive=day_positive)
        assert applied.trust == pytest.approx(0.01)

    def test_case_10_thirty_days_user_care(self):
        state = make_state()
        for _ in range(8):
            state, applied = apply(state, "user_care", day_positive=RelationshipDelta())
            assert applied.trust >= 0
        assert state.trust == pytest.approx(0.35 + 8 * 0.04, abs=1e-6)
        assert state.trust >= 0.6

    def test_case_10_stage_progression_with_intimacy(self):
        state = make_state()
        for _ in range(10):
            state, _ = apply(state, "intimate_moment", day_positive=RelationshipDelta())
        assert state.intimacy >= 0.55
        assert state.trust >= 0.55
        assert state.stage == "close_friend"
