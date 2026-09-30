from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from typing import get_args

from app.models.character_state import CharacterEmotion, EmotionLabel, Mood
from app.models.emotion import EmotionEvent
from app.engines.state import EMOTION_EVENTS, MAGNITUDE_COEFFICIENTS


class TestCharacterEmotion:
    def test_defaults(self):
        emotion = CharacterEmotion()
        assert emotion.primary_emotion == "calm"
        assert emotion.intensity == 0.3
        assert emotion.cause == ""
        assert emotion.updated_at is None

    def test_valid_custom_values(self):
        emotion = CharacterEmotion(
            primary_emotion="happy",
            intensity=0.85,
            cause="用户主动关心角色",
            updated_at=datetime.now(timezone.utc),
        )
        assert emotion.primary_emotion == "happy"
        assert emotion.intensity == 0.85

    def test_all_eight_labels_valid(self):
        for label in ("happy", "sad", "angry", "worried", "shy", "excited", "tired", "calm"):
            assert CharacterEmotion(primary_emotion=label).primary_emotion == label

    def test_invalid_label_rejected(self):
        with pytest.raises(ValidationError):
            CharacterEmotion(primary_emotion="embarrassed")
        with pytest.raises(ValidationError):
            CharacterEmotion(primary_emotion="neutral")
        with pytest.raises(ValidationError):
            CharacterEmotion(primary_emotion="furious")

    def test_intensity_out_of_range_rejected(self):
        for bad in (-0.01, 1.01, 100, -2):
            with pytest.raises(ValidationError):
                CharacterEmotion(intensity=bad)

    def test_intensity_boundaries_accepted(self):
        assert CharacterEmotion(intensity=0.0).intensity == 0.0
        assert CharacterEmotion(intensity=1.0).intensity == 1.0

    def test_cause_max_length_enforced(self):
        assert len(CharacterEmotion(cause="好" * 50).cause) == 50
        with pytest.raises(ValidationError):
            CharacterEmotion(cause="好" * 51)


class TestEmotionEvent:
    def test_defaults(self):
        event = EmotionEvent()
        assert event.type == "none"
        assert event.magnitude == "normal"
        assert event.confidence == 0.0
        assert event.cause == ""

    def test_valid_event(self):
        event = EmotionEvent(
            type="praise", magnitude="strong", confidence=0.9, cause="用户夸角色"
        )
        assert event.type == "praise"
        assert event.magnitude == "strong"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            EmotionEvent(type="betrayal")

    def test_invalid_magnitude_rejected(self):
        with pytest.raises(ValidationError):
            EmotionEvent(magnitude="huge")

    def test_confidence_out_of_range_rejected(self):
        for bad in (-0.1, 1.1):
            with pytest.raises(ValidationError):
                EmotionEvent(confidence=bad)


class TestEmotionEventTable:
    def test_all_non_none_event_types_covered(self):
        expected = {
            "praise", "comforted", "criticized", "teased", "conflict",
            "warm_moment", "funny_moment", "worrying_news", "reunion",
        }
        assert set(EMOTION_EVENTS) == expected
        assert "none" not in EMOTION_EVENTS

    def test_mapped_emotions_are_valid_labels(self):
        valid_labels = set(get_args(EmotionLabel))
        for spec in EMOTION_EVENTS.values():
            assert spec["emotion"] in valid_labels

    def test_deltas_within_unit_range(self):
        for spec in EMOTION_EVENTS.values():
            assert 0.0 <= spec["delta"] <= 1.0

    def test_conflict_has_largest_delta(self):
        assert EMOTION_EVENTS["conflict"]["delta"] == 0.4

    def test_magnitude_coefficients(self):
        assert MAGNITUDE_COEFFICIENTS == {"weak": 0.6, "normal": 1.0, "strong": 1.4}


class TestV2Compat:
    def test_emotion_label_matches_v2_mood(self):
        assert EmotionLabel == Mood
