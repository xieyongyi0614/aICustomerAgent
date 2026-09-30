from datetime import datetime, timedelta

import pytest

from app.models.character_state import CharacterState
from app.models.emotion import EmotionEvent
from app.engines import state as state_engine


def make_state(**overrides):
    payload = {
        "mood": "calm",
        "intensity": 0.3,
        "cause": "",
        "energy": 0.9,
    }
    payload.update(overrides)
    return CharacterState(**payload)


def make_event(**overrides):
    payload = {
        "type": "praise",
        "magnitude": "normal",
        "confidence": 0.9,
        "cause": "用户夸奖角色",
    }
    payload.update(overrides)
    return EmotionEvent(**payload)


NOW = datetime(2026, 8, 29, 12, 0, 0)


class TestEventMapping:
    def test_praise_raises_happy(self):
        result = state_engine.update_emotion(make_state(), make_event(), NOW)
        assert result.mood == "happy"
        assert result.intensity == pytest_approx(0.3 + 0.3 * 0.2)

    def test_criticized_makes_sad(self):
        result = state_engine.update_emotion(
            make_state(), make_event(type="criticized"), NOW
        )
        assert result.mood == "sad"

    def test_conflict_makes_angry_with_strong_delta(self):
        result = state_engine.update_emotion(
            make_state(), make_event(type="conflict"), NOW
        )
        assert result.mood == "angry"
        assert result.intensity == pytest_approx(0.4 + 0.3 * 0.2)

    def test_magnitude_scales_delta(self):
        weak = state_engine.update_emotion(
            make_state(), make_event(magnitude="weak"), NOW
        )
        strong = state_engine.update_emotion(
            make_state(), make_event(magnitude="strong"), NOW
        )
        assert weak.intensity == pytest_approx(0.18 + 0.3 * 0.2)
        assert strong.intensity == pytest_approx(0.42 + 0.3 * 0.2)


def pytest_approx(value):
    return round(value, 6)


class TestSwitchAndInertia:
    def test_switch_keeps_20_percent_inertia(self):
        result = state_engine.update_emotion(
            make_state(mood="calm", intensity=0.5), make_event(), NOW
        )
        assert result.mood == "happy"
        assert result.intensity == pytest_approx(0.3 + 0.1)

    def test_none_event_only_decays(self):
        result = state_engine.update_emotion(
            make_state(mood="happy", intensity=0.5, last_event_at=NOW - timedelta(hours=1)),
            make_event(type="none"),
            NOW,
        )
        assert result.mood == "happy"
        assert result.intensity == pytest.approx(0.4)

    def test_cause_updated(self):
        result = state_engine.update_emotion(
            make_state(), make_event(cause="因为你刚才夸我"), NOW
        )
        assert result.cause == "因为你刚才夸我"

    def test_empty_cause_keeps_previous(self):
        result = state_engine.update_emotion(
            make_state(cause="旧成因"), make_event(cause=""), NOW
        )
        assert result.cause == "旧成因"

    def test_last_event_and_updated_at_refreshed(self):
        result = state_engine.update_emotion(make_state(), make_event(), NOW)
        assert result.last_event_at == NOW
        assert result.updated_at == NOW


class TestStrongEmotionProtection:
    def test_strong_emotion_blocks_low_confidence_switch(self):
        state = make_state(mood="happy", intensity=0.7)
        result = state_engine.update_emotion(
            state, make_event(type="criticized", confidence=0.7), NOW
        )
        assert result.mood == "happy"
        assert result.intensity == 0.7
        assert result.last_event_at is None

    def test_strong_emotion_allows_high_confidence_switch(self):
        state = make_state(mood="happy", intensity=0.7)
        result = state_engine.update_emotion(
            state, make_event(type="criticized", confidence=0.9), NOW
        )
        assert result.mood == "sad"

    def test_weak_emotion_allows_low_confidence_switch(self):
        state = make_state(mood="happy", intensity=0.4)
        result = state_engine.update_emotion(
            state, make_event(type="criticized", confidence=0.5), NOW
        )
        assert result.mood == "sad"

    def test_strong_emotion_same_target_still_stacks(self):
        state = make_state(mood="happy", intensity=0.7)
        result = state_engine.update_emotion(
            state, make_event(type="praise", confidence=0.5), NOW
        )
        assert result.mood == "happy"
        assert result.intensity > 0.7


class TestAntiJump:
    def test_turn_delta_capped_at_0_4(self):
        state = make_state(mood="calm", intensity=0.1)
        result = state_engine.update_emotion(
            state, make_event(type="conflict", magnitude="strong"), NOW
        )
        assert result.intensity == pytest_approx(0.5)

    def test_max_turn_delta_respected_from_settings(self, monkeypatch):
        class StrictSettings:
            emotion_max_turn_delta = 0.2
            emotion_strong_threshold = 0.6
            emotion_switch_min_confidence = 0.8
            emotion_inertia = 0.2
            emotion_decay_strong = 0.20
            emotion_decay_mild = 0.10
            emotion_decay_floor = 0.15
            emotion_rest_intensity = 0.3
            emotion_strong_boundary = 0.5

        monkeypatch.setattr(state_engine, "get_settings", lambda: StrictSettings())
        state = make_state(mood="calm", intensity=0.1)
        result = state_engine.update_emotion(
            state, make_event(type="conflict", magnitude="strong"), NOW
        )
        assert result.intensity == pytest.approx(0.3, abs=1e-9)


class TestBounds:
    def test_intensity_never_exceeds_one(self):
        result = state_engine.update_emotion(
            make_state(mood="happy", intensity=0.95),
            make_event(magnitude="strong"),
            NOW,
        )
        assert result.intensity <= 1.0

    def test_intensity_never_negative(self):
        result = state_engine.update_emotion(
            make_state(mood="happy", intensity=0.05),
            make_event(type="criticized", magnitude="weak", confidence=0.9),
            NOW,
        )
        assert result.intensity >= 0.0
