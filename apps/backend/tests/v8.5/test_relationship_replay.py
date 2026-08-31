"""V8.5 M3 重放/回滚基础套件（evolution-engine.md §6 / persistence.md §5）。

replay(state_0, stream) = state_t；回滚 = 关键帧 + 其后账本重放（前向修正）。
"""

import random

from app.models.relationship import (
    RelationshipDelta,
    RelationshipEvent,
    RelationshipState,
)
from app.services import relationship_evolution as revo

EVENT_TYPES = ("user_care", "praise", "intimate_moment", "conflict", "criticized", "long_interaction")
MAGNITUDES = ("weak", "normal", "strong")


def _random_event(seed: int) -> RelationshipEvent:
    rng = random.Random(seed)
    from datetime import datetime

    event_type = EVENT_TYPES[rng.randrange(len(EVENT_TYPES))]
    magnitude = MAGNITUDES[rng.randrange(len(MAGNITUDES))]
    base = {
        "user_care": RelationshipDelta(trust=0.04, intimacy=0.03, comfort=0.03),
        "praise": RelationshipDelta(trust=0.02, intimacy=0.02, comfort=0.01),
        "intimate_moment": RelationshipDelta(trust=0.02, intimacy=0.06, comfort=0.04),
        "conflict": RelationshipDelta(trust=-0.10, intimacy=-0.12, tension=0.20),
        "criticized": RelationshipDelta(trust=-0.03, tension=0.05),
        "long_interaction": RelationshipDelta(intimacy=0.01, familiarity=0.02, comfort=0.01),
    }[event_type]
    coef = {"weak": 0.6, "normal": 1.0, "strong": 1.4}[magnitude]
    impact = RelationshipDelta(
        **{dim: getattr(base, dim) * coef for dim in ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")}
    )
    return RelationshipEvent(
        user_id="u1", session_id="s1", type=event_type, magnitude=magnitude,
        impact=impact, confidence=0.8, created_at=datetime(2026, 8, 31, 12, 0, 0),
    )


def test_replay_deterministic_across_random_streams():
    start = RelationshipState()
    for i in range(100):
        events = [_random_event(i * 1000 + j) for j in range(50)]
        first = revo.replay(start, events)
        second = revo.replay(start, events)
        assert first == second
        assert first.version == 50


def test_replay_truncation_prefix_consistency():
    start = RelationshipState()
    events = [_random_event(i) for i in range(30)]
    full = revo.replay(start, events)
    prefix = revo.replay(start, events[:15])
    later = revo.replay(prefix, events[15:])
    assert later == full


def test_replay_state_matches_incremental_application():
    """replay(state_0, stream) 与逐事件前向应用一致（版本单调）。"""
    start = RelationshipState(version=5)
    events = [_random_event(i) for i in range(20)]
    replayed = revo.replay(start, events)
    assert replayed.version == start.version + 20
    assert all(
        getattr(replayed, dim) >= 0.0 and getattr(replayed, dim) <= 1.0
        for dim in ("intimacy", "trust", "familiarity", "respect", "comfort", "tension")
    )