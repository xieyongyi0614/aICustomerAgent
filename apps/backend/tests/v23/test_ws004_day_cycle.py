"""WS-004：DayCycleEngine 日循环标记测试。"""

from datetime import datetime

import pytest

from app.application import world_engine
from app.core.settings import get_settings
from app.models.world import TimeContext, WorldTimeMode
from app.repositories import world_repository, world_simulation_repository
from app.services.world import day_cycle

pytestmark = pytest.mark.xdist_group("ws004")


def _ctx(now: datetime) -> TimeContext:
    return TimeContext(
        now=now,
        weekday="周三",
        part_of_day=_part(now),
        time_mode=WorldTimeMode.REAL_SYNC,
    )


def _part(now: datetime) -> str:
    from app.models.world import part_of_day

    return part_of_day(now)


@pytest.fixture
def sim_mode(monkeypatch):
    monkeypatch.setenv("WORLD_TIME_MODE", "simulated")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sim_world(user_id: str, sim_time: datetime):
    world = world_repository.ensure_world(user_id)
    world_simulation_repository.commit_time_advance(world.world_id, sim_time, sim_time)
    return world_repository.get_world(user_id)


def test_cold_start_emits_only_day_start():
    curr = _ctx(datetime(2026, 9, 14, 15, 0))
    drafts = day_cycle.compute_due_markers(None, curr)
    assert [d.key for d in drafts] == ["time:day_start:2026-09-14"]


def test_part_transition_same_day():
    prev = _ctx(datetime(2026, 9, 14, 10, 0))
    curr = _ctx(datetime(2026, 9, 14, 15, 0))
    drafts = day_cycle.compute_due_markers(prev, curr)
    keys = [d.key for d in drafts]
    assert keys == ["time:part:2026-09-14:dusk"]
    assert drafts[0].payload["from_part"] == "morning"
    assert drafts[0].payload["to_part"] == "dusk"


def test_day_boundary_closes_previous_and_starts_new():
    prev = _ctx(datetime(2026, 9, 14, 23, 30))
    curr = _ctx(datetime(2026, 9, 15, 9, 0))
    drafts = day_cycle.compute_due_markers(prev, curr)
    keys = [d.key for d in drafts]
    assert keys == [
        "time:day_close:2026-09-14",
        "time:day_start:2026-09-15",
        "time:part:2026-09-15:morning",
    ]


def test_week_boundary_added():
    prev = _ctx(datetime(2026, 9, 13, 20, 0))
    curr = _ctx(datetime(2026, 9, 14, 9, 0))
    keys = [d.key for d in day_cycle.compute_due_markers(prev, curr)]
    assert "time:week:2026-W38" in keys


def test_no_change_no_markers():
    same = _ctx(datetime(2026, 9, 14, 15, 0))
    assert day_cycle.compute_due_markers(same, same) == []


def test_emit_idempotent_across_ticks(db_session_factory, sim_mode):
    user = "ws004-emit"
    _sim_world(user, datetime(2026, 9, 14, 15, 0))
    day_cycle.reset_observation(user)

    first = day_cycle.emit_time_markers(user)
    assert first == ["time:day_start:2026-09-14"]

    second = day_cycle.emit_time_markers(user)
    assert second == []

    day_cycle.reset_observation(user)
    third = day_cycle.emit_time_markers(user)
    assert third == []

    _sim_world(user, datetime(2026, 9, 15, 9, 30))
    fourth = day_cycle.emit_time_markers(user)
    assert set(fourth) == {
        "time:day_close:2026-09-14",
        "time:day_start:2026-09-15",
        "time:part:2026-09-15:morning",
    }


def test_emitted_events_are_completed_time_markers(db_session_factory, sim_mode):
    user = "ws004-shape"
    world = _sim_world(user, datetime(2026, 9, 14, 15, 0))
    day_cycle.reset_observation(user)
    day_cycle.emit_time_markers(user)
    events = world_repository.list_events(world.world_id, limit=10)
    assert events
    for event in events:
        assert event.type == "time_marker"
        assert event.source.value == "time"
        assert event.status.value == "completed"
        assert event.idempotency_key


def test_maintenance_step_emits_markers(monkeypatch, db_session_factory):
    monkeypatch.setenv("V23_WORLD_SIMULATION_ENABLED", "true")
    monkeypatch.setenv("V23_TIME_ADVANCE_ENABLED", "true")
    get_settings.cache_clear()
    try:
        user = "ws004-maint"
        _sim_world(user, datetime(2026, 9, 14, 15, 0))
        day_cycle.reset_observation(user)
        results = world_engine.run_simulation_maintenance(user)
        assert results
        world = world_repository.get_world(user)
        events = world_repository.list_events(world.world_id, limit=10)
        assert any(e.idempotency_key == "time:day_start:2026-09-14" for e in events)
    finally:
        get_settings.cache_clear()
