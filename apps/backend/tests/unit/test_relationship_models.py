from typing import get_args
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.relationship import (
    RelationshipDelta,
    RelationshipEventType,
    RelationshipState,
)
from app.repositories import relationship_repository
from app.services.state_engine import RELATIONSHIP_EVENT_DELTAS


class TestRelationshipStateTension:
    def test_tension_defaults_zero(self):
        state = RelationshipState()
        assert state.tension == 0.0

    def test_v2_dimensions_unchanged(self):
        state = RelationshipState()
        assert state.intimacy == 0.3
        assert state.trust == 0.35
        assert state.familiarity == 0.3
        assert state.stage == "friend"

    def test_tension_out_of_range_rejected(self):
        for bad in (-0.01, 1.01):
            with pytest.raises(ValidationError):
                RelationshipState(tension=bad)

    def test_tension_boundaries_accepted(self):
        assert RelationshipState(tension=0.0).tension == 0.0
        assert RelationshipState(tension=1.0).tension == 1.0


class TestRelationshipEventType:
    def test_all_twelve_types_valid(self):
        expected = {
            "user_care", "user_help", "intimate_moment", "long_interaction",
            "praise", "criticized", "conflict", "boundary_violation", "promise_kept", "promise_broken", "warm_moment", "none",
        }
        assert set(get_args(RelationshipEventType)) == expected


class TestRelationshipEventDeltas:
    def test_all_event_types_have_delta_entries(self):
        assert set(get_args(RelationshipEventType)) <= set(RELATIONSHIP_EVENT_DELTAS)

    def test_emotion_warm_moment_also_has_delta_entry(self):
        assert "warm_moment" in RELATIONSHIP_EVENT_DELTAS

    def test_positive_events_reduce_tension(self):
        for name in ("user_care", "intimate_moment", "praise", "warm_moment"):
            assert RELATIONSHIP_EVENT_DELTAS[name].tension < 0

    def test_negative_events_raise_tension(self):
        assert RELATIONSHIP_EVENT_DELTAS["conflict"].tension == 0.20
        assert RELATIONSHIP_EVENT_DELTAS["criticized"].tension == 0.05
        assert RELATIONSHIP_EVENT_DELTAS["boundary_violation"].tension == 0.15

    def test_conflict_is_most_damaging(self):
        conflict = RELATIONSHIP_EVENT_DELTAS["conflict"]
        assert conflict.trust == -0.10
        assert conflict.intimacy == -0.12
        assert conflict.familiarity == -0.05

    def test_user_care_builds_trust(self):
        delta = RELATIONSHIP_EVENT_DELTAS["user_care"]
        assert delta.trust == 0.04
        assert delta.intimacy == 0.03
        assert delta.familiarity == 0.01
        assert delta.tension == -0.02

    def test_none_event_zero_deltas(self):
        delta = RELATIONSHIP_EVENT_DELTAS["none"]
        assert delta.model_dump() == {
            "intimacy": 0.0,
            "trust": 0.0,
            "familiarity": 0.0,
            "respect": 0.0,
            "comfort": 0.0,
            "tension": 0.0,
        }

    def test_single_event_delta_stays_within_documented_caps(self):
        for delta in RELATIONSHIP_EVENT_DELTAS.values():
            for field in ("intimacy", "trust", "familiarity", "tension"):
                assert abs(getattr(delta, field)) <= 0.2


class TestRepositoryTension:
    def test_tension_roundtrip(self, db_session_factory):
        saved = relationship_repository.upsert_relationship(
            "u1",
            RelationshipState(tension=0.4, intimacy=0.5, trust=0.6),
        )
        assert saved.tension == 0.4
        loaded = relationship_repository.get_relationship("u1")
        assert loaded.tension == 0.4

    def test_v2_rows_default_tension_zero(self, db_session_factory):
        relationship_repository.upsert_relationship(
            "u2", RelationshipState(intimacy=0.5, trust=0.5, familiarity=0.4)
        )
        loaded = relationship_repository.get_relationship("u2")
        assert loaded.tension == 0.0

    def test_delta_model_carries_tension(self):
        delta = RelationshipDelta(tension=-0.02)
        assert delta.tension == -0.02
        assert delta.trust == 0.0


class TestDateTimeCompat:
    def test_updated_at_roundtrip(self, db_session_factory):
        relationship_repository.upsert_relationship(
            "u3", RelationshipState(tension=0.1)
        )
        loaded = relationship_repository.get_relationship("u3")
        assert isinstance(loaded.updated_at, datetime)
        assert loaded.updated_at.tzinfo is None or loaded.updated_at < datetime.now(timezone.utc).replace(tzinfo=None)
