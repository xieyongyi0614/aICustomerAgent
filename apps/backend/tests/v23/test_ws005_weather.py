"""WS-005：CalendarAsset 与 WeatherEvolver 测试。"""

from datetime import date, datetime

import pytest

from app.application import world_engine
from app.character.asuna.calendar import holiday_of, season_of
from app.character.asuna.world import WORLD_WEATHER_VALUES
from app.core.settings import get_settings
from app.repositories import world_repository, world_simulation_repository
from app.services.world import day_cycle, weather

pytestmark = pytest.mark.xdist_group("ws005")


@pytest.fixture
def sim_mode(monkeypatch):
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_season_boundaries():
    assert season_of(date(2026, 2, 28)) == "winter"
    assert season_of(date(2026, 3, 1)) == "spring"
    assert season_of(date(2026, 8, 31)) == "summer"
    assert season_of(date(2026, 12, 31)) == "winter"


def test_holiday_lookup():
    assert holiday_of(date(2026, 10, 1))["name"] == "国庆节"
    assert holiday_of(date(2026, 12, 25))["kind"] == "festival"
    assert holiday_of(date(2026, 7, 11)) is None


def test_weather_enum_aligned_with_asset():
    for season in ("spring", "summer", "autumn", "winter"):
        for candidate in weather._TRANSITIONS[season]:
            for target, _ in weather._TRANSITIONS[season][candidate]:
                assert target in WORLD_WEATHER_VALUES


def test_evolve_deterministic_replay():
    day = date(2026, 9, 14)
    first = weather.evolve("sunny", "autumn", day, "home:u1")
    second = weather.evolve("sunny", "autumn", day, "home:u1")
    assert first == second
    assert first[0] in WORLD_WEATHER_VALUES
    other_day = weather.evolve("sunny", "autumn", date(2026, 9, 15), "home:u1")
    assert isinstance(other_day[1], float)


def test_evolve_directional_by_season():
    winter_days = [
        weather.evolve("cloudy", "winter", date(2026, 1, d), "home:u1")[0]
        for d in range(1, 28)
    ]
    assert "snow" in winter_days
    summer_days = [
        weather.evolve("cloudy", "summer", date(2026, 7, d), "home:u1")[0]
        for d in range(1, 28)
    ]
    assert "snow" not in summer_days


def test_evolve_falls_back_on_unknown_prev():
    next_weather, _ = weather.evolve(" sandstorm", "autumn", date(2026, 9, 14), "home:u1")
    assert next_weather == weather.BASELINE_WEATHER["autumn"]


def test_daily_weather_orchestration_idempotent(db_session_factory, sim_mode):
    user = "ws005-orch"
    world = world_repository.ensure_world(user)
    world_simulation_repository.commit_time_advance(
        world.world_id, datetime(2026, 9, 14, 9, 0), datetime(2026, 9, 14, 9, 0)
    )
    first = weather.evolve_daily_weather(user)
    assert first == "weather:2026-09-14"
    stored = world_repository.get_world(user)
    assert stored.environment.weather in WORLD_WEATHER_VALUES
    assert stored.environment.updated_by == "weather_sim"
    assert weather.evolve_daily_weather(user) is None

    events = world_repository.list_events(world.world_id, limit=10)
    weather_events = [e for e in events if e.type == "weather_change"]
    assert len(weather_events) == 1
    assert weather_events[0].idempotency_key == "weather:2026-09-14"


def test_maintenance_step_evolves_weather(monkeypatch, db_session_factory, sim_mode):
    monkeypatch.setenv("WORLD_SIMULATION_ENABLED", "true")
    monkeypatch.setenv("TIME_ADVANCE_ENABLED", "true")
    get_settings.cache_clear()
    try:
        user = "ws005-maint"
        world = world_repository.ensure_world(user)
        world_simulation_repository.commit_time_advance(
            world.world_id, datetime(2026, 9, 14, 9, 0), datetime(2026, 9, 14, 9, 0)
        )
        world_engine.run_simulation_maintenance(user)
        stored = world_repository.get_world(user)
        assert stored.environment.weather is not None
        events = world_repository.list_events(world.world_id, limit=10)
        assert any(e.type == "weather_change" for e in events)
    finally:
        get_settings.cache_clear()


def test_season_and_holiday_markers(db_session_factory, sim_mode):
    user = "ws005-markers"
    world = world_repository.ensure_world(user)
    world_simulation_repository.commit_time_advance(
        world.world_id, datetime(2026, 11, 30, 20, 0), datetime(2026, 11, 30, 20, 0)
    )
    day_cycle.reset_observation(user)
    day_cycle.emit_time_markers(user)
    world_simulation_repository.commit_time_advance(
        world.world_id, datetime(2026, 12, 25, 9, 0), datetime(2026, 12, 25, 9, 0)
    )
    emitted = day_cycle.emit_time_markers(user)
    assert "time:season:2026-12-25" in emitted
    assert "calendar:2026-12-25" in emitted
    events = world_repository.list_events(world.world_id, limit=20)
    holiday_events = [e for e in events if e.type == "calendar_event"]
    assert holiday_events and holiday_events[0].payload["name"] == "圣诞节"
    assert holiday_events[0].source.value == "calendar"
