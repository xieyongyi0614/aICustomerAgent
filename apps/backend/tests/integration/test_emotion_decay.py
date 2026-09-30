from datetime import datetime, timedelta

import pytest

from app.repositories import character_state_repository
from app.engines import state as state_engine
from app.services.conversation import state as state_service
from app.models.character_state import CharacterState


NOW = datetime(2026, 8, 29, 12, 0, 0)


def make_state(**overrides):
    payload = {
        "mood": "happy",
        "intensity": 0.55,
        "cause": "用户夸奖",
        "last_event_at": NOW - timedelta(minutes=30),
    }
    payload.update(overrides)
    return CharacterState(**payload)


class TestDecayCurve:
    def test_strong_emotion_decays_faster_than_mild(self):
        strong = state_engine.apply_emotion_decay(
            make_state(intensity=0.55, last_event_at=NOW - timedelta(hours=1)), NOW
        )
        mild = state_engine.apply_emotion_decay(
            make_state(intensity=0.45, last_event_at=NOW - timedelta(hours=1)), NOW
        )
        assert strong.intensity == pytest.approx(0.55 - 0.20, abs=1e-9)
        assert mild.intensity == pytest.approx(0.45 - 0.10, abs=1e-9)

    def test_doc_case_1_5_hours_055_happy(self):
        result = state_engine.apply_emotion_decay(
            make_state(intensity=0.55, last_event_at=NOW - timedelta(hours=1.5)), NOW
        )
        assert result.mood == "happy"
        assert result.intensity == pytest.approx(0.25, abs=0.05)

    def test_no_event_time_no_decay(self):
        state = make_state(last_event_at=None, intensity=0.9)
        assert state_engine.apply_emotion_decay(state, NOW) == state

    def test_future_event_time_no_decay(self):
        state = make_state(last_event_at=NOW + timedelta(hours=1))
        assert state_engine.apply_emotion_decay(state, NOW) == state

    def test_zero_elapsed_no_decay(self):
        state = make_state(last_event_at=NOW)
        assert state_engine.apply_emotion_decay(state, NOW) == state


class TestFloorReset:
    def test_decay_to_floor_resets_to_calm(self):
        result = state_engine.apply_emotion_decay(
            make_state(intensity=0.5, last_event_at=NOW - timedelta(hours=4)), NOW
        )
        assert result.mood == "calm"
        assert result.intensity == 0.3
        assert result.cause == ""

    def test_above_floor_keeps_emotion_and_cause(self):
        result = state_engine.apply_emotion_decay(
            make_state(intensity=0.55, last_event_at=NOW - timedelta(hours=1)), NOW
        )
        assert result.mood == "happy"
        assert result.cause == "用户夸奖"

    def test_cross_day_single_step_calculation(self):
        result = state_engine.apply_emotion_decay(
            make_state(intensity=0.8, last_event_at=NOW - timedelta(days=3)), NOW
        )
        assert result.mood == "calm"
        assert result.intensity == 0.3


class TestReadingSideDecay:
    def test_load_states_decays_and_persists(self, db_session_factory):
        event_at = datetime.now() - timedelta(hours=1)
        character_state_repository.upsert_state(
            "u1",
            CharacterState(mood="happy", intensity=0.55, cause="夸奖", last_event_at=event_at),
        )
        character, _ = state_service.load_states("u1")
        assert character.intensity == pytest.approx(0.35, abs=0.05)
        assert character.mood == "happy"
        persisted = character_state_repository.get_state("u1")
        assert persisted.intensity == pytest.approx(character.intensity, abs=1e-9)

    def test_load_states_without_change_no_write(self, db_session_factory):
        character_state_repository.upsert_state(
            "u2", CharacterState(mood="calm", intensity=0.3, last_event_at=None)
        )
        character, _ = state_service.load_states("u2")
        assert character.intensity == 0.3
        assert character.mood == "calm"
