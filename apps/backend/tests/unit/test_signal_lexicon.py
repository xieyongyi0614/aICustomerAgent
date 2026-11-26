"""V8.5 M2 信号词表单测（tests/unit/test_signal_lexicon.py）。

敏感类（越界/冲突/批评）宁误报不漏报；恢复词表不产信号（M5 消费）。
"""

from app.character.asuna.relationship_lexicon import (
    RECOVERY_LEXICON,
    SENSITIVE_LEXICON,
    SIGNAL_LEXICON,
    describe_comfort,
    describe_respect,
)
from app.engines import relationship_signal as rs


def test_sensitive_lexicon_must_not_miss():
    for patterns, kind, quality, _ in SENSITIVE_LEXICON:
        for pattern in patterns:
            signal = rs.detect_heuristic(f"我真想对你说{pattern}")
            assert signal is not None, pattern
            assert signal.quality == "negative", pattern


def test_recovery_lexicon_does_not_emit_signal():
    for phrase in RECOVERY_LEXICON:
        message = f"我只想说{phrase}"
        signal = rs.detect_heuristic(message)
        if signal is not None:
            assert signal.kind != "recovery"


def test_lexicon_entries_are_wellformed():
    for patterns, kind, quality, salience in SIGNAL_LEXICON:
        assert kind in {
            entry[1] for entry in SIGNAL_LEXICON
        }
        assert quality in ("positive", "neutral", "negative")
        assert 0.0 < salience <= 1.0
        assert patterns


def test_signal_matrix_covers_all_lexicon_kinds():
    matrix_kinds = {kind for kind, _ in rs.SIGNAL_EVENT_MATRIX}
    lexicon_kinds = {entry[1] for entry in SIGNAL_LEXICON}
    assert lexicon_kinds <= matrix_kinds


def test_level_texts_three_bands():
    assert describe_respect(0.2) == "言行让你有些失望"
    assert describe_respect(0.6) == "保持应有的尊重"
    assert describe_respect(0.9) == "由衷敬佩"
    assert describe_comfort(0.2) == "相处有些放不开"
    assert describe_comfort(0.6) == "相处还算自在"
    assert describe_comfort(0.9) == "相处毫无负担"