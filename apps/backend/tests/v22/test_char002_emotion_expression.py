"""CHAR-002：情绪 → 表达约束映射单测（纯函数，无 IO / 无 LLM）。"""

import pytest

from app.character.asuna.emotion_expression import EMOTION_TONES
from app.models.behavior_strategy import MOOD_KEYS
from app.models.character_state import CharacterState
from app.services.experience.emotion_expression import (
    build_emotion_expression,
    describe_transition,
    expression_intensity_tier,
)


def _state(mood: str, intensity: float) -> CharacterState:
    return CharacterState(mood=mood, intensity=intensity)


@pytest.mark.parametrize("mood", MOOD_KEYS)
def test_every_mood_maps_to_deterministic_expression(mood):
    expression = build_emotion_expression(_state(mood, 0.5))
    assert expression == build_emotion_expression(_state(mood, 0.5))
    assert expression.tone_directive == EMOTION_TONES.tones[mood].tone_directive
    assert expression.tone_directive != ""
    assert len(expression.tone_directive) <= 30
    assert expression.channel_bias == EMOTION_TONES.tones[mood].channel_bias


def test_intensity_tier_boundaries():
    assert expression_intensity_tier(0.0) == "subtle"
    assert expression_intensity_tier(0.3) == "subtle"
    assert expression_intensity_tier(0.31) == "natural"
    assert expression_intensity_tier(0.6) == "natural"
    assert expression_intensity_tier(0.61) == "rich"
    assert expression_intensity_tier(1.0) == "rich"


def test_build_emotion_expression_default_state_is_subtle_calm():
    expression = build_emotion_expression(CharacterState())
    assert expression.channel_bias == "balanced"
    assert expression.expression_intensity == "subtle"
    assert expression.tone_directive != ""


def test_intensity_boost_upgrades_tier():
    expression = build_emotion_expression(_state("worried", 0.55), intensity_boost=0.2)
    assert expression.expression_intensity == "rich"


def test_intensity_boost_negative_downgrades_tier():
    expression = build_emotion_expression(_state("happy", 0.5), intensity_boost=-0.3)
    assert expression.expression_intensity == "subtle"


def test_intensity_boost_clamped_to_unit_range():
    boosted = build_emotion_expression(_state("excited", 0.9), intensity_boost=0.5)
    assert boosted.expression_intensity == "rich"
    lowered = build_emotion_expression(_state("sad", 0.1), intensity_boost=-0.5)
    assert lowered.expression_intensity == "subtle"


def test_describe_transition_cross_mood():
    text = describe_transition(_state("calm", 0.3), _state("worried", 0.55))
    assert text == "calm → worried（0.30→0.55）"


def test_describe_transition_same_mood_intensity_change():
    text = describe_transition(_state("happy", 0.4), _state("happy", 0.7))
    assert text == "happy（0.40→0.70）"


def test_describe_transition_no_change_returns_empty():
    assert describe_transition(_state("calm", 0.3), _state("calm", 0.3)) == ""


def test_describe_transition_to_full_intensity():
    text = describe_transition(_state("calm", 0.3), _state("angry", 1.0))
    assert text == "calm → angry（0.30→1.00）"
