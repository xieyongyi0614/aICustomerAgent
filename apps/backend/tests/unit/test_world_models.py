from datetime import datetime

import pytest

from app.core.settings import SettingsError, get_settings
from app.models.world import (
    EventImportance,
    EventSource,
    EventStatus,
    ObjectStatus,
    TimeContext,
    WorldContext,
    WorldEnvironment,
    WorldEvent,
    WorldFacts,
    WorldObject,
    WorldTimeMode,
    bounded_notes,
    part_of_day,
)


def _object(**overrides) -> WorldObject:
    defaults = {
        "id": "watermelon_001",
        "world_id": "home:default-user",
        "name": "西瓜",
        "category": "food",
        "location_id": "home.kitchen.fridge",
        "state": "whole",
        "quantity": 1.0,
    }
    defaults.update(overrides)
    return WorldObject(**defaults)


def test_world_object_defaults_and_status():
    obj = _object()
    assert obj.status is ObjectStatus.ACTIVE
    assert obj.quantity == 1.0
    assert obj.brief() == {
        "name": "西瓜",
        "location_id": "home.kitchen.fridge",
        "state": "whole",
        "quantity": 1.0,
    }
    with pytest.raises(ValueError):
        _object(quantity=-0.1)


def test_world_event_brief_due_in_hours():
    now = datetime(2026, 9, 1, 10, 0)
    event = WorldEvent(
        id="evt-1",
        world_id="home:default-user",
        type="interview",
        title="用户的面试",
        importance=EventImportance.HIGH,
        due_at=datetime(2026, 9, 2, 10, 0),
    )
    assert event.status is EventStatus.SCHEDULED
    assert event.source is EventSource.USER_MENTION
    brief = event.brief(now)
    assert brief["due_in_hours"] == 24.0
    completed = event.model_copy(
        update={"status": EventStatus.COMPLETED, "completed_at": now}
    )
    assert completed.brief(now)["due_in_hours"] is None


def test_part_of_day_boundaries():
    def at(hour):
        return datetime(2026, 9, 1, hour, 0)

    assert part_of_day(at(5)) == "morning"
    assert part_of_day(at(10)) == "morning"
    assert part_of_day(at(11)) == "afternoon"
    assert part_of_day(at(13)) == "afternoon"
    assert part_of_day(at(14)) == "dusk"
    assert part_of_day(at(17)) == "dusk"
    assert part_of_day(at(18)) == "evening"
    assert part_of_day(at(22)) == "evening"
    assert part_of_day(at(23)) == "late_night"
    assert part_of_day(at(3)) == "late_night"


def test_time_context_day_line():
    context = TimeContext(
        now=datetime(2026, 8, 31, 23, 40),
        weekday="周一",
        part_of_day="late_night",
        time_mode=WorldTimeMode.REAL_SYNC,
    )
    assert "周一" in context.day_line()
    assert "23:40" in context.day_line()
    assert "深夜" in context.day_line()


def test_world_context_defaults():
    context = WorldContext(
        time=TimeContext(
            now=datetime.now(), weekday="周一", part_of_day="morning", time_mode=WorldTimeMode.REAL_SYNC
        ),
        location={
            "current": "home.living_room",
            "current_name": "客厅",
            "path": ["家", "客厅"],
            "available_actions": [],
            "traits": [],
        },
    )
    assert context.nearby_objects == []
    assert context.salient_events == []
    assert context.environment is None


def test_bounded_notes_respects_budget():
    notes = ["一" * 100, "二" * 100, "三" * 100]
    bounded = bounded_notes(notes, 150)
    assert sum(len(note) for note in bounded) <= 150
    assert bounded_notes([], 100) == []


def test_world_environment_defaults():
    env = WorldEnvironment()
    assert env.weather is None
    assert env.updated_by is None


def test_world_facts_defaults():
    facts = WorldFacts()
    assert facts.weather is None
    assert facts.salient_events == []


def test_world_settings_defaults(monkeypatch):
    monkeypatch.delenv("WORLD_ENABLED", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.world_enabled is True
    assert settings.world_time_mode == "real_sync"
    assert settings.world_context_char_budget == 600
    assert "world_llm_assist_enabled" not in type(settings).model_fields
    assert settings.world_memory_importance()["normal"] == 0.6
    get_settings.cache_clear()


def test_world_settings_validation(monkeypatch):
    monkeypatch.setenv("WORLD_TIME_MODE", "warp")
    get_settings.cache_clear()
    with pytest.raises(SettingsError, match="WORLD_TIME_MODE"):
        get_settings()
    get_settings.cache_clear()
    monkeypatch.delenv("WORLD_TIME_MODE")

    monkeypatch.setenv("WORLD_SIM_RATE", "0")
    get_settings.cache_clear()
    with pytest.raises(SettingsError, match="WORLD_SIM_RATE"):
        get_settings()
    get_settings.cache_clear()
    monkeypatch.delenv("WORLD_SIM_RATE")

    monkeypatch.setenv("WORLD_MEMORY_IMPORTANCE_JSON", "[]")
    get_settings.cache_clear()
    with pytest.raises(SettingsError, match="WORLD_MEMORY_IMPORTANCE_JSON"):
        get_settings()
    get_settings.cache_clear()
