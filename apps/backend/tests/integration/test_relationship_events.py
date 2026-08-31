from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.relationship import RelationshipDelta, RelationshipEvent
from app.repositories import relationship_event_repository as repo
from app.repositories import relationship_repository
from app.services import state_engine


NOW = datetime(2026, 8, 29, 12, 0, 0)


def make_event(**overrides):
    payload = {
        "user_id": "u1",
        "session_id": "s1",
        "type": "user_care",
        "magnitude": "normal",
        "impact": RelationshipDelta(trust=0.04, intimacy=0.03, familiarity=0.01, tension=-0.02),
        "confidence": 0.9,
        "cause": "用户主动关心角色",
        "created_at": NOW,
    }
    payload.update(overrides)
    return RelationshipEvent(**payload)


class TestEventBuilder:
    def test_user_care_normal_impact(self):
        impact = state_engine.build_relationship_impact("user_care", "normal")
        assert impact.trust == pytest.approx(0.04)
        assert impact.intimacy == pytest.approx(0.03)
        assert impact.familiarity == pytest.approx(0.01)
        assert impact.tension == pytest.approx(-0.02)

    def test_strong_scales_by_1_4(self):
        impact = state_engine.build_relationship_impact("user_help", "strong")
        assert impact.trust == pytest.approx(0.07)

    def test_weak_scales_by_0_6(self):
        impact = state_engine.build_relationship_impact("conflict", "weak")
        assert impact.trust == pytest.approx(-0.06)
        assert impact.tension == pytest.approx(0.12)

    def test_none_event_zero_impact(self):
        impact = state_engine.build_relationship_impact("none", "normal")
        assert impact.model_dump() == {
            "intimacy": 0.0,
            "trust": 0.0,
            "familiarity": 0.0,
            "respect": 0.0,
            "comfort": 0.0,
            "tension": 0.0,
        }

    def test_unknown_event_type_raises(self):
        with pytest.raises(KeyError):
            state_engine.build_relationship_impact("betrayal", "normal")


class TestRelationshipEventModel:
    def test_default_source_and_id(self):
        event = make_event()
        assert event.source == "conversation"
        assert event.character_id == "asuna"
        assert len(event.id) == 36

    def test_invalid_source_rejected(self):
        with pytest.raises(ValidationError):
            make_event(source="somewhere")

    def test_memory_replay_source_valid(self):
        assert make_event(source="memory_replay").source == "memory_replay"

    def test_confidence_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            make_event(confidence=1.5)


class TestRepository:
    def test_create_and_get_roundtrip(self, db_session_factory):
        event = repo.create_event(make_event())
        assert event.id == repo.list_events("u1")[0].id
        stored = repo.list_events("u1")[0]
        assert stored.type == "user_care"
        assert stored.impact.trust == pytest.approx(0.04)
        assert stored.impact.tension == pytest.approx(-0.02)
        assert stored.source == "conversation"

    def test_list_user_isolated_and_ordered_desc(self, db_session_factory):
        older = repo.create_event(
            make_event(created_at=NOW - timedelta(hours=2))
        )
        newer = repo.create_event(
            make_event(type="conflict", created_at=NOW - timedelta(hours=1))
        )
        events = repo.list_events("u1")
        assert [e.id for e in events] == [newer.id, older.id]
        assert repo.list_events("u2") == []

    def test_count_events(self, db_session_factory):
        repo.create_event(make_event())
        repo.create_event(make_event(type="conflict"))
        assert repo.count_events("u1") == 2
        assert repo.count_events("u2") == 0

    def test_memory_replay_source_persisted(self, db_session_factory):
        repo.create_event(make_event(source="memory_replay", type="user_help"))
        stored = repo.list_events("u1")[0]
        assert stored.source == "memory_replay"


class TestCombinedCommit:
    def test_commit_relationship_update_writes_state_and_events(self, db_session_factory):
        from app.models.relationship import RelationshipState

        relationship = RelationshipState(
            intimacy=0.5, trust=0.6, familiarity=0.4, tension=0.2
        )
        event = make_event(user_id="u-combined")
        saved = relationship_repository.commit_relationship_update(
            "u-combined", relationship, [event]
        )
        assert saved.trust == 0.6
        assert saved.tension == 0.2
        assert repo.list_events("u-combined")[0].type == "user_care"

    def test_commit_relationship_update_atomic_on_failure(
        self, db_session_factory, monkeypatch
    ):
        from app.models.relationship import RelationshipState

        relationship = RelationshipState(trust=0.6)
        event = make_event(user_id="u-combined")
        real_session_local = relationship_repository.SessionLocal

        def failing_session():
            session = real_session_local()
            session.commit = lambda: (_ for _ in ()).throw(RuntimeError("commit down"))
            return session

        monkeypatch.setattr(relationship_repository, "SessionLocal", failing_session)
        with pytest.raises(RuntimeError):
            relationship_repository.commit_relationship_update(
                "u-combined", relationship, [event]
            )
        assert relationship_repository.get_relationship("u-combined").trust == 0.35
        assert repo.list_events("u-combined") == []
