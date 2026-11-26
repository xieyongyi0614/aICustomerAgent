"""V8.5 M3 演化引擎单测（evolution-engine.md 验收标准，含 0.0063 精确值）。"""

from datetime import datetime

from app.models.relationship import InteractionSignal, RelationshipDelta, RelationshipState
from app.engines import relationship_evolution as revo
from app.engines import relationship_signal as rs


def _state(**overrides) -> RelationshipState:
    values = dict(
        intimacy=0.3, trust=0.6, familiarity=0.3, respect=0.6, comfort=0.6,
        tension=0.0, stage="friend",
    )
    values.update(overrides)
    return RelationshipState(**values)


def _signal(kind="gratitude", quality="positive", salience=0.5):
    return InteractionSignal(kind=kind, quality=quality, salience=salience)


NOW = datetime(2026, 8, 31, 12, 0, 0)


def test_doc_example_third_thanks_trust_00063():
    state = _state()
    base = RelationshipDelta(trust=0.02)
    dynamics, flags = revo.apply_dynamics(
        base, state, {("gratitude", "positive"): 2}, _signal()
    )
    assert flags.get("d1_repetition") is True
    assert flags.get("d2_saturation") is True
    assert dynamics.trust < 0.0064
    assert dynamics.trust > 0.0062


def test_d1_only_positive():
    base = RelationshipDelta(trust=-0.02)
    dynamics, flags = revo.apply_dynamics(
        base, _state(), {("conflict", "negative"): 5}, _signal("conflict", "negative")
    )
    assert "d1_repetition" not in flags
    assert abs(dynamics.trust - (-0.03)) < 1e-9


def test_d2_familiarity_exempt():
    base = RelationshipDelta(familiarity=0.02)
    dynamics, flags = revo.apply_dynamics(
        base, _state(familiarity=0.95), {}, _signal()
    )
    assert flags == {"d5_salience": True}
    assert abs(dynamics.familiarity - 0.02) < 1e-9


def test_d3_trust_negative_amplified():
    base = RelationshipDelta(trust=-0.02)
    dynamics, _ = revo.apply_dynamics(base, _state(), {}, _signal("conflict", "negative"))
    assert abs(dynamics.trust - (-0.03)) < 1e-9


def test_d4_comfort_exempt_from_d1_d2():
    base = RelationshipDelta(comfort=0.03)
    dynamics, flags = revo.apply_dynamics(
        base, _state(comfort=0.95), {("gratitude", "positive"): 5}, _signal()
    )
    assert flags == {"d5_salience": True}
    assert abs(dynamics.comfort - 0.03) < 1e-9


def test_d5_salience_modulation():
    base = RelationshipDelta(trust=0.04)
    low = revo.apply_dynamics(base, _state(trust=0.0), {}, _signal(salience=0.0))[0]
    high = revo.apply_dynamics(base, _state(trust=0.0), {}, _signal(salience=0.9))[0]
    assert abs(low.trust - 0.04) < 1e-9
    assert abs(high.trust - 0.056) < 1e-9


def test_rate_limit_turn_cap():
    limited, truncated = revo.rate_limit(
        _state(), RelationshipDelta(trust=0.5), RelationshipDelta(),
        RelationshipDelta(), RelationshipDelta(),
    )
    assert limited.trust <= 0.15
    assert "trust" in truncated


def test_rate_limit_day_headroom():
    day = RelationshipDelta(trust=0.28)
    limited, _ = revo.rate_limit(
        _state(), RelationshipDelta(trust=0.1), RelationshipDelta(), day, RelationshipDelta()
    )
    assert abs(limited.trust - 0.02) < 1e-9


def test_comfort_drift_toward_baseline():
    _, applied = revo.apply_comfort_drift(_state(comfort=0.6), False)
    assert applied == 0.0
    _, applied = revo.apply_comfort_drift(_state(stage="partner", comfort=0.6), False)
    assert applied > 0
    _, applied = revo.apply_comfort_drift(_state(stage="stranger", comfort=0.6), False)
    assert applied < 0


def test_comfort_drift_conflict_penalty():
    normal = revo.comfort_baseline("friend", False)
    conflict = revo.comfort_baseline("friend", True)
    assert abs(normal - conflict - 0.10) < 1e-9


def test_evolve_writes_event_and_version():
    state = _state(version=3)
    new_state, outcome = revo.evolve(
        state, "praise", "normal", "comfort", _signal(), {},
        RelationshipDelta(), RelationshipDelta(), NOW,
        session_id="s1", user_id="u1", cause="被夸", confidence=0.5,
    )
    assert outcome.event is not None
    assert outcome.event.type == "praise"
    assert new_state.version == 4
    assert outcome.applied_delta.trust > 0


def test_evolve_none_event_no_ledger_row():
    new_state, outcome = revo.evolve(
        _state(), "none", "normal", "comfort", None, {},
        RelationshipDelta(), RelationshipDelta(), NOW,
    )
    assert outcome.event is None
    assert new_state.version == 1


def test_evolve_stage_insensitive_to_new_dimensions():
    state = _state(intimacy=0.55, trust=0.55, familiarity=0.35, respect=0.99, comfort=0.99)
    new_state, _ = revo.evolve(
        state, "long_interaction", "weak", "comfort", None, {},
        RelationshipDelta(), RelationshipDelta(), NOW,
    )
    assert new_state.stage == "close_friend"


def test_replay_deterministic():
    from app.models.relationship import RelationshipEvent

    events = [
        RelationshipEvent(
            user_id="u", session_id="s", type="praise", magnitude="normal",
            impact=RelationshipDelta(trust=0.02, intimacy=0.01), confidence=0.5,
            created_at=NOW,
        ),
        RelationshipEvent(
            user_id="u", session_id="s", type="conflict", magnitude="normal",
            impact=RelationshipDelta(trust=-0.10, tension=0.20), confidence=0.9,
            created_at=NOW,
        ),
    ]
    start = _state()
    assert revo.replay(start, events) == revo.replay(start, events)
    assert revo.replay(start, events).version == 2


def test_distance_index_boundaries():
    low = revo.distance_index(
        _state(tension=0.0, comfort=1.0, last_interaction_at=NOW), NOW
    )
    assert low == 0.0
    high = revo.distance_index(
        _state(tension=1.0, comfort=0.0, last_interaction_at=None), NOW
    )
    assert high == 1.0


def test_signal_window_snapshot_roundtrip():
    window = rs.EvidenceWindow(capacity=5)
    window.record(_signal())
    assert window.snapshot() == (("gratitude", "positive"),)


def test_humor_maps_to_warm_moment_event_row():
    event_type, magnitude = rs.map_signal_to_event(_signal("humor", salience=0.5))
    assert event_type == "warm_moment"
    state, outcome = revo.evolve(
        _state(),
        event_type,
        magnitude,
        "normal_reply",
        _signal("humor", salience=0.5),
        {},
        RelationshipDelta(),
        RelationshipDelta(),
        NOW,
        session_id="s",
        user_id="u",
        cause="玩笑互动",
        confidence=0.5,
    )
    assert outcome.event is not None
    assert outcome.event.type == "warm_moment"
    assert state.version == 1