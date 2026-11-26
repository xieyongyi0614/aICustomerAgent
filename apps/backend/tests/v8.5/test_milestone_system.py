"""V8.5 M4 里程碑系统套件（milestone-system.md 验收标准）。"""

from datetime import datetime

import pytest

from app.models.relationship import RelationshipDelta, RelationshipState
from app.repositories import relationship_milestone_repository
from app.services.relationship import milestone as rms

NOW = datetime(2026, 8, 31, 12, 0, 0)


def _ctx(**overrides) -> rms.MilestoneContext:
    before = RelationshipState(stage="friend")
    values = dict(
        user_id="u-ms",
        event_type="none",
        state_before=before,
        state_after=before,
        stage_before="friend",
        stage_after="friend",
        ledger_empty_before=False,
        now=NOW,
    )
    values.update(overrides)
    return rms.MilestoneContext(**values)


class TestPredicates:
    def test_first_interaction_requires_empty_ledger(self):
        assert rms.MILESTONES[0].detect(_ctx(ledger_empty_before=True)) is True
        assert rms.MILESTONES[0].detect(_ctx(ledger_empty_before=False)) is False

    def test_first_self_disclosure(self):
        spec = rms.keyed("first_self_disclosure")
        assert spec.detect(_ctx(event_type="intimate_moment")) is True
        assert spec.detect(_ctx(event_type="praise")) is False

    def test_first_support_in_distress_requires_negative_mood(self):
        spec = rms.keyed("first_support_in_distress")
        assert spec.detect(
            _ctx(event_type="user_care", character_mood="sad", character_intensity=0.8)
        )
        assert not spec.detect(
            _ctx(event_type="user_care", character_mood="happy", character_intensity=0.8)
        )
        assert not spec.detect(
            _ctx(event_type="user_care", character_mood="sad", character_intensity=0.5)
        )

    def test_first_conflict(self):
        spec = rms.keyed("first_conflict")
        assert spec.detect(_ctx(event_type="conflict")) is True
        assert spec.detect(_ctx(event_type="criticized")) is False

    def test_first_apology_and_forgiveness(self):
        assert rms.keyed("first_apology").detect(_ctx(conflict_transition="recovery_started"))
        assert not rms.keyed("first_apology").detect(_ctx(conflict_transition="cold_started"))
        assert rms.keyed("first_forgiveness").detect(_ctx(conflict_transition="reconciled"))

    def test_stage_transitions(self):
        assert rms.keyed("stage_close_friend").detect(
            _ctx(stage_before="friend", stage_after="close_friend")
        )
        assert not rms.keyed("stage_close_friend").detect(
            _ctx(stage_before="close_friend", stage_after="close_friend")
        )

    def test_monthly_anniversary_period(self):
        spec = rms.keyed("monthly_anniversary")
        assert spec.detect(_ctx(first_interaction_month="2026-07"))
        assert not spec.detect(_ctx(first_interaction_month="2026-08"))

    def test_twelve_specs_registered(self):
        assert len(rms.MILESTONES) == 12


class TestBonusCap:
    def test_bonus_capped_at_010(self):
        capped = rms._cap_bonus(RelationshipDelta(trust=0.5, comfort=-0.02))
        assert capped.trust == pytest.approx(0.10)
        assert capped.comfort == pytest.approx(-0.02)

    def test_no_bonus_for_negative_milestone(self):
        spec = rms.keyed("first_conflict")
        assert spec.bonus.trust == 0.0 and spec.bonus.intimacy == 0.0


def test_process_milestone_unique_idempotent(db_session_factory):
    ctx = _ctx(event_type="conflict")
    state = RelationshipState(stage="friend")
    updated, records = rms.process_milestones(ctx, state)
    assert [r.milestone_key for r in records] == ["first_conflict"]
    again_state, again_records = rms.process_milestones(ctx, updated)
    assert again_records == []
    existing = relationship_milestone_repository.existing_keys("u-ms")
    assert ("first_conflict", "") in existing


def test_process_milestone_bonus_applied(db_session_factory):
    ctx = _ctx(event_type="intimate_moment")
    state = RelationshipState(stage="friend")
    updated, records = rms.process_milestones(ctx, state)
    keys = {r.milestone_key for r in records}
    assert "first_self_disclosure" in keys
    assert updated.trust == pytest.approx(state.trust + 0.03)
    assert "emotional_support_deep" in records[0].unlocks


def test_unlock_query(db_session_factory):
    ctx = _ctx(event_type="conflict")
    rms.process_milestones(ctx, RelationshipState(stage="friend"))
    assert relationship_milestone_repository.has_unlock(
        "u-ms", "conflict_recovery_available"
    )
    assert not relationship_milestone_repository.has_unlock("u-ms", "proactive_goodnight")