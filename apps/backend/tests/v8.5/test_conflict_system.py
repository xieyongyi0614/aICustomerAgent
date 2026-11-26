"""V8.5 M5 conflict system suite (conflict-system.md)."""

from datetime import datetime, timedelta

import pytest

from app.models.relationship import (
    ConflictRecord,
    RelationshipDelta,
    RelationshipEvent,
    RelationshipState,
)
from app.engines import relationship_conflict as rconf

NOW = datetime(2026, 8, 31, 12, 0, 0)


def _state(**overrides) -> RelationshipState:
    values = dict(
        intimacy=0.3, trust=0.35, familiarity=0.3, respect=0.6, comfort=0.6,
        tension=0.0, stage="friend", conflict_status="none",
    )
    values.update(overrides)
    return RelationshipState(**values)


def _event(type_="conflict", impact=None) -> RelationshipEvent:
    return RelationshipEvent(
        user_id="u1", session_id="s1", type=type_, magnitude="normal",
        impact=impact or RelationshipDelta(tension=0.2, trust=-0.1),
        confidence=0.9, created_at=NOW,
    )


def _record(status="conflict", started=None, last_negative=None, recovery_started=None) -> ConflictRecord:
    return ConflictRecord(
        user_id="u1", status=status,
        started_at=started or NOW - timedelta(hours=24),
        last_negative_at=last_negative or NOW - timedelta(hours=1),
        recovery_started_at=recovery_started,
        created_at=started or NOW - timedelta(hours=24),
    )


def _eval(state, record, events, message="你好"):
    return rconf.evaluate_conflict("u1", "s1", state, record, events, message, NOW)


class TestTransitionMatrix:
    def test_none_to_conflict_on_event(self):
        outcome = _eval(_state(), None, [_event()])
        assert outcome.record is not None and outcome.record.status == "conflict"

    def test_none_to_strain_on_tension_freeze(self):
        outcome = _eval(_state(tension=0.6), None, [])
        assert outcome.record.status == "strain"

    def test_none_to_strain_on_two_negatives(self):
        outcome = _eval(_state(), None, [_event("criticized"), _event("criticized")])
        assert outcome.record.status == "strain"

    def test_illegal_none_to_resolved_rejected(self):
        outcome = _eval(_state(), None, [])
        assert outcome.record is None and outcome.transition == ""

    def test_strain_to_conflict(self):
        outcome = _eval(_state(), _record("strain"), [_event()])
        assert outcome.record.status == "conflict"

    def test_strain_relief_after_48h_calm(self):
        record = _record("strain", last_negative=NOW - timedelta(hours=49))
        outcome = _eval(_state(tension=0.1), record, [])
        assert outcome.record.status == "resolved"

    def test_strain_recovery_word_softens_tension_only(self):
        record = _record("strain", last_negative=NOW - timedelta(hours=1))
        outcome = _eval(_state(tension=0.4), record, [], message="对不起，我错了")
        assert outcome.record.status == "strain"
        assert outcome.state.tension == pytest.approx(0.38)

    def test_conflict_to_cold_after_12h(self):
        record = _record("conflict", last_negative=NOW - timedelta(hours=13))
        outcome = _eval(_state(), record, [])
        assert outcome.record.status == "cold"

    def test_conflict_not_cold_before_12h(self):
        record = _record("conflict", last_negative=NOW - timedelta(hours=2))
        outcome = _eval(_state(), record, [])
        assert outcome.record.status == "conflict"

    def test_conflict_recovery_on_apology(self):
        record = _record("conflict", last_negative=NOW - timedelta(hours=2))
        outcome = _eval(_state(), record, [], message="对不起")
        assert outcome.record.status == "recovery"

    def test_recovery_needs_two_positives_to_resolve(self):
        record = _record("recovery", recovery_started=NOW - timedelta(hours=1))
        outcome = _eval(_state(tension=0.4, comfort=0.4), record, [
            _event("user_care", RelationshipDelta(trust=0.04, comfort=0.03)),
            _event("praise", RelationshipDelta(trust=0.02)),
        ])
        assert outcome.record.status == "resolved"
        assert outcome.record.resolution == "reconciled"
        assert outcome.state.tension == pytest.approx(0.2)
        assert outcome.state.comfort == pytest.approx(0.45)

    def test_recovery_single_positive_not_resolved(self):
        record = _record("recovery", recovery_started=NOW - timedelta(hours=1))
        outcome = _eval(_state(), record, [_event("praise", RelationshipDelta(trust=0.02))])
        assert outcome.record.status == "recovery"

    def test_recovery_fallback_after_7d_silence(self):
        record = _record("recovery", recovery_started=NOW - timedelta(days=8))
        outcome = _eval(_state(), record, [])
        assert outcome.record.status == "cold"

    def test_resolved_reopens_on_new_conflict(self):
        closed = _record("conflict")
        closed.status = "resolved"
        closed.resolved_at = NOW
        outcome = _eval(_state(), closed, [_event()])
        assert outcome.transition == "conflict_reopened"
        assert outcome.record.id != closed.id

    def test_cold_negative_refreshes_timer(self):
        record = _record("conflict", last_negative=NOW - timedelta(hours=13))
        outcome = _eval(_state(), record, [_event("criticized")])
        assert outcome.record.last_negative_at == NOW


class TestNeglect:
    def test_neglect_threshold_by_stage(self):
        for stage, threshold in (
            ("stranger", 7), ("friend", 5), ("close_friend", 3), ("partner", 2),
        ):
            state = _state(stage=stage, last_interaction_at=NOW - timedelta(days=threshold + 1))
            outcome = rconf.detect_neglect("u1", "s1", state, False, NOW)
            assert outcome.state.neglect_active is True, stage

    def test_neglect_trust_drop_only_deep_stages(self):
        shallow = rconf.detect_neglect(
            "u1", "s1",
            _state(stage="friend", last_interaction_at=NOW - timedelta(days=6)), False, NOW,
        )
        deep = rconf.detect_neglect(
            "u1", "s1",
            _state(stage="partner", last_interaction_at=NOW - timedelta(days=3)), False, NOW,
        )
        assert shallow.state.trust == pytest.approx(0.35)
        assert deep.state.trust == pytest.approx(0.34)

    def test_reunion_resets_neglect(self):
        state = _state(stage="partner", neglect_active=True)
        outcome = rconf.detect_neglect("u1", "s1", state, True, NOW)
        assert outcome.state.neglect_active is False

    def test_neglect_not_retriggered_while_active(self):
        state = _state(neglect_active=True, last_interaction_at=NOW - timedelta(days=10))
        outcome = rconf.detect_neglect("u1", "s1", state, False, NOW)
        assert outcome.system_events == []


class TestTensionDecay:
    def test_decay_scales_with_gap_days(self):
        state = _state(tension=0.5, last_interaction_at=NOW - timedelta(days=1))
        outcome = rconf.decay_tension("u1", "s1", state, None, NOW)
        assert outcome.state.tension == pytest.approx(0.48)
        state = _state(tension=0.5, last_interaction_at=NOW - timedelta(days=5))
        outcome = rconf.decay_tension("u1", "s1", state, None, NOW)
        assert outcome.state.tension == pytest.approx(0.4)

    def test_decay_same_day_noop(self):
        state = _state(tension=0.5, last_interaction_at=NOW)
        outcome = rconf.decay_tension("u1", "s1", state, None, NOW)
        assert outcome.state.tension == 0.5
        assert outcome.system_events == []

    def test_decay_paused_in_active_conflict(self):
        state = _state(tension=0.5, last_interaction_at=NOW - timedelta(days=1))
        outcome = rconf.decay_tension("u1", "s1", state, _record("cold"), NOW)
        assert outcome.state.tension == 0.5

    def test_decay_system_event_is_ledgered(self):
        state = _state(tension=0.5, last_interaction_at=NOW - timedelta(days=1))
        outcome = rconf.decay_tension("u1", "s1", state, None, NOW)
        assert outcome.system_events[0].source == "system"
        assert outcome.system_events[0].impact.tension == pytest.approx(-0.02)