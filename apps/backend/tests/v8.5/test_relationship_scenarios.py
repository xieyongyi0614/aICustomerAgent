"""V8.5 M9 长期演化场景套件（testing.md：30 天累计 / 冲突全生命周期 / 疏远→召回 / 性能护栏）。

时间敏感全部注入时钟；性能预算：单次演化 <10ms、派生指标批 <25ms。
"""

import time
from datetime import datetime, timedelta

import pytest

from app.models.autonomy import AutonomyVerdict, TriggerSignal
from app.models.relationship import (
    ConflictRecord,
    RelationshipDelta,
    RelationshipEvent,
    RelationshipState,
)
from app.services import relationship_conflict as rconf
from app.services import relationship_evolution as revo
from app.services.autonomy_policy import PolicySnapshot, _apply_relationship_rules
from app.core.settings import get_settings

START = datetime(2026, 8, 1, 12, 0, 0)
DIMENSIONS = ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")


def _state(**overrides) -> RelationshipState:
    values = dict(
        intimacy=0.3, trust=0.35, familiarity=0.3, respect=0.6, comfort=0.6,
        tension=0.0, stage="friend",
    )
    values.update(overrides)
    return RelationshipState(**values)


def _event(type_="praise", impact=None, at=START) -> RelationshipEvent:
    return RelationshipEvent(
        user_id="u1", session_id="s1", type=type_, magnitude="normal",
        impact=impact or RelationshipDelta(trust=0.02, comfort=0.01),
        confidence=0.9, created_at=at,
    )


def _record(status="conflict", at=START, **overrides) -> ConflictRecord:
    values = dict(
        user_id="u1", status=status, started_at=at, last_negative_at=at,
        created_at=at,
    )
    values.update(overrides)
    return ConflictRecord(**values)


class TestThirtyDayCumulative:
    def test_trust_grows_monotonically_within_caps(self):
        settings = get_settings()
        state = _state()
        for day in range(30):
            state, outcome = revo.evolve(
                state,
                event_type="praise",
                magnitude="normal",
                behavior="natural_continuation",
                signal=None,
                repeats_by_kind={},
                day_positive=RelationshipDelta(),
                day_negative=RelationshipDelta(),
                now=START + timedelta(days=day),
                user_id="u1",
                session_id="s1",
                cause="日常互动",
            )
            for dim in DIMENSIONS:
                applied = getattr(outcome.applied_delta, dim)
                assert abs(applied) <= settings.rel_max_turn_delta + 1e-9, (day, dim)
        assert state.trust > 0.35
        assert state.intimacy >= 0.3
        for dim in DIMENSIONS:
            assert 0.0 <= getattr(state, dim) <= 1.0
        assert state.version == 30

    def test_cumulative_stream_replayable(self):
        state = _state()
        events = []
        for day in range(20):
            state, outcome = revo.evolve(
                state,
                event_type="user_care" if day % 2 == 0 else "long_interaction",
                magnitude="weak",
                behavior="natural_continuation",
                signal=None,
                repeats_by_kind={},
                day_positive=RelationshipDelta(),
                day_negative=RelationshipDelta(),
                now=START + timedelta(days=day),
                user_id="u1",
                session_id="s1",
            )
            if outcome.event is not None:
                events.append(outcome.event)
        replayed = revo.replay(_state(), events)
        for dim in ("intimacy", "trust", "familiarity", "respect", "tension"):
            assert getattr(replayed, dim) == pytest.approx(getattr(state, dim), abs=0.05), dim

    def test_repetition_decay_slows_accumulation(self):
        early = _state()
        for day in range(10):
            early, _ = revo.evolve(
                early, "praise", "normal", "natural_continuation", None,
                {("praise", "normal"): day}, RelationshipDelta(), RelationshipDelta(),
                now=START + timedelta(days=day),
            )
        fresh, first = revo.evolve(
            _state(), "praise", "normal", "natural_continuation", None,
            {}, RelationshipDelta(), RelationshipDelta(), now=START,
        )
        _, tenth = revo.evolve(
            early, "praise", "normal", "natural_continuation", None,
            {("praise", "normal"): 10}, RelationshipDelta(), RelationshipDelta(),
            now=START + timedelta(days=10),
        )
        assert abs(tenth.applied_delta.trust) < abs(first.applied_delta.trust)


class TestConflictFullLifecycle:
    def test_strain_to_conflict_to_cold_to_recovery_to_resolved(self):
        state = _state(tension=0.6)
        transitions = []

        outcome = rconf.evaluate_conflict(
            "u1", "s1", state, None,
            [_event("criticized"), _event("criticized")], "", START,
        )
        transitions.append(outcome.record.status)
        record = outcome.record

        rconf.evaluate_conflict(
            "u1", "s1", state, record, [_event("conflict")], "",
            START + timedelta(hours=1),
        )
        assert record.status == "conflict"
        transitions.append("conflict")

        rconf.evaluate_conflict(
            "u1", "s1", state, record, [], "",
            START + timedelta(hours=14),
        )
        assert record.status == "cold"
        transitions.append("cold")

        rconf.evaluate_conflict(
            "u1", "s1", state, record, [], "对不起，那天是我不对",
            START + timedelta(hours=14, minutes=1),
        )
        assert record.status == "recovery"
        transitions.append("recovery")

        outcome = rconf.evaluate_conflict(
            "u1", "s1", state, record,
            [_event("user_care", RelationshipDelta(trust=0.02)),
             _event("praise", RelationshipDelta(trust=0.02))],
            "", START + timedelta(hours=15),
        )
        assert record.status == "resolved"
        transitions.append("resolved")

        assert transitions == ["strain", "conflict", "cold", "recovery", "resolved"]
        assert outcome.transition == "reconciled"
        assert outcome.state.comfort == pytest.approx(_state().comfort + 0.05)

    def test_resolved_state_tension_settled(self):
        state = _state(tension=0.6)
        record = _record("recovery", at=START - timedelta(hours=2))
        outcome = rconf.evaluate_conflict(
            "u1", "s1", state, record,
            [_event("user_care", RelationshipDelta(trust=0.02)),
             _event("praise", RelationshipDelta(trust=0.02))],
            "", START,
        )
        assert record.status == "resolved"
        assert outcome.state.tension == pytest.approx(0.3)
        assert outcome.system_events[0].source == "system"


class TestEstrangementAndRecall:
    def test_neglect_then_autonomy_recall_then_reunion(self):
        state = _state(stage="partner", last_interaction_at=START - timedelta(days=4))
        outcome = rconf.detect_neglect("u1", "s1", state, False, START)
        assert outcome.state.neglect_active is True
        assert outcome.state.comfort == pytest.approx(0.55)
        assert outcome.state.trust == pytest.approx(0.34)
        assert outcome.system_events[0].source == "system"

        snapshot = PolicySnapshot(
            selected_goal_type="user_care",
            trust=0.30,
            stage="partner",
            neglect_active=True,
            last_proactive_at=START - timedelta(hours=6),
        )
        verdict = AutonomyVerdict(
            decision="act", reason="触发 conversation_inactivity",
            trigger=TriggerSignal(
                type="conversation_inactivity", user_id="u1",
                detected_at=START, dedupe_key="d1",
            ),
            intention="reminder",
        )
        gated = _apply_relationship_rules(verdict, snapshot, get_settings())
        assert gated.decision == "act"
        assert "R5疏远召回覆盖R3" in gated.reason

        reunion = rconf.detect_neglect(
            "u1", "s1", outcome.state, True, START + timedelta(days=1)
        )
        assert reunion.state.neglect_active is False

    def test_shallow_stage_neglect_no_trust_penalty(self):
        state = _state(stage="stranger", last_interaction_at=START - timedelta(days=8))
        outcome = rconf.detect_neglect("u1", "s1", state, False, START)
        assert outcome.state.neglect_active is True
        assert outcome.state.trust == pytest.approx(0.35)
        assert outcome.state.comfort == pytest.approx(0.55)


class TestPerformanceGuard:
    def test_evolve_under_10ms_average(self):
        state = _state()
        start = time.perf_counter()
        for day in range(200):
            state, _ = revo.evolve(
                state, "praise", "weak", "natural_continuation", None,
                {("praise", "weak"): day % 5}, RelationshipDelta(), RelationshipDelta(),
                now=START + timedelta(days=day % 30),
            )
        elapsed_ms = (time.perf_counter() - start) / 200 * 1000
        assert elapsed_ms < 10.0, elapsed_ms

    def test_derived_metrics_batch_under_25ms(self):
        state = _state()
        start = time.perf_counter()
        for day in range(100):
            revo.distance_index(state, START + timedelta(days=day))
            revo.comfort_baseline("friend", conflict_active=False)
        elapsed_ms = (time.perf_counter() - start) / 100 * 1000
        assert elapsed_ms < 25.0, elapsed_ms
