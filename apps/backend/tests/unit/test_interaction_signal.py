"""V8.5 M2 交互信号单测（interaction-analysis.md 验收标准）。"""

from app.models.emotion import TurnAnalysis
from app.models.relationship import InteractionSignal
from app.engines import relationship_signal as rs


def _signal(kind, quality="positive", salience=0.6):
    return InteractionSignal(kind=kind, quality=quality, salience=salience)


def test_heuristic_gratitude_hit():
    signal = rs.detect_heuristic("今天多亏了你，太感谢了")
    assert signal is not None
    assert signal.kind == "gratitude"
    assert signal.quality == "positive"
    assert signal.salience == 0.5


def test_heuristic_self_disclosure_hit():
    signal = rs.detect_heuristic("说真的，其实我一直很在意那件事")
    assert signal is not None
    assert signal.kind == "self_disclosure"
    assert signal.salience == 0.6


def test_heuristic_negative_priority_over_positive():
    signal = rs.detect_heuristic("谢谢你啊，但你少管我")
    assert signal is not None
    assert signal.kind == "boundary_violation"
    assert signal.quality == "negative"


def test_heuristic_no_hit_returns_none():
    assert rs.detect_heuristic("今天天气不错") is None


def test_llm_field_priority_over_heuristic():
    analysis = TurnAnalysis(
        interaction_signal=_signal("support", salience=0.8)
    )
    signal = rs.analyze_interaction("多亏了你", analysis)
    assert signal is not None
    assert signal.kind == "support"
    assert signal.salience == 0.8


def test_llm_field_missing_falls_back_to_lexicon():
    signal = rs.analyze_interaction("多亏了你", TurnAnalysis())
    assert signal is not None
    assert signal.kind == "gratitude"


def test_llm_field_invalid_kind_falls_back():
    analysis = TurnAnalysis(
        interaction_signal=InteractionSignal(kind="smalltalk", quality="neutral")
    )
    signal = rs.analyze_interaction("多亏了你", analysis)
    assert signal is not None
    assert signal.kind == "gratitude"


def test_mapping_matrix_positive_paths():
    cases = {
        "self_disclosure": "intimate_moment",
        "support": "user_care",
        "gratitude": "praise",
        "appreciation": "praise",
        "humor": "warm_moment",
        "shared_activity": "long_interaction",
        "request_help": "user_care",
        "teaching": "user_help",
    }
    for kind, event_type in cases.items():
        event, magnitude = rs.map_signal_to_event(_signal(kind))
        assert event == event_type, kind
        assert magnitude == "normal"


def test_mapping_magnitude_salience_bands():
    assert rs.map_signal_to_event(_signal("self_disclosure", salience=0.8))[1] == "strong"
    assert rs.map_signal_to_event(_signal("self_disclosure", salience=0.5))[1] == "normal"
    assert rs.map_signal_to_event(_signal("self_disclosure", salience=0.2))[1] == "weak"


def test_mapping_conflict_strong_band():
    assert rs.map_signal_to_event(_signal("conflict", "negative", 0.8))[1] == "strong"
    assert rs.map_signal_to_event(_signal("conflict", "negative", 0.5))[1] == "normal"


def test_mapping_promise_outcome_semantics():
    assert rs.map_signal_to_event(_signal("promise", "positive"))[0] == "promise_kept"
    assert rs.map_signal_to_event(_signal("promise", "negative"))[0] == "promise_broken"


def test_mapping_boundary_violation_floor_normal():
    assert rs.map_signal_to_event(_signal("boundary_violation", "negative", 0.7))[1] == "strong"
    assert rs.map_signal_to_event(_signal("boundary_violation", "negative", 0.5))[1] == "normal"


def test_mapping_neutral_degrades_to_weak():
    event, magnitude = rs.map_signal_to_event(_signal("support", "neutral"))
    assert event == "user_care"
    assert magnitude == "weak"


def test_mapping_smalltalk_always_weak():
    _, magnitude = rs.map_signal_to_event(_signal("smalltalk", salience=0.9))
    assert magnitude == "weak"


def test_mapping_none_signal():
    assert rs.map_signal_to_event(None) == ("none", "normal")


def test_novelty_sequence():
    assert rs.novelty_for(0) == 1.0
    assert rs.novelty_for(1) == 0.5
    assert rs.novelty_for(3) == 0.25


def test_evidence_window_counts_and_capacity():
    window = rs.EvidenceWindow(capacity=3)
    for _ in range(5):
        window.record(_signal("gratitude"))
    assert window.count("gratitude", "positive") == 3
    assert len(window.snapshot()) == 3


def test_observe_fills_novelty():
    window = rs.EvidenceWindow(capacity=20)
    first = rs.observe(window, _signal("gratitude"))
    second = rs.observe(window, _signal("gratitude"))
    assert first.novelty == 1.0
    assert second.novelty == 0.5


def test_window_rebuild_equivalent_on_kind_counts():
    class _Event:
        def __init__(self, type_, magnitude):
            self.type = type_
            self.magnitude = magnitude

    events = [_Event("praise", "normal"), _Event("praise", "strong")]
    window = rs.EvidenceWindow.rebuild_from_events(events)
    assert window.count("gratitude", "neutral") == 1
    assert window.count("gratitude", "positive") == 1