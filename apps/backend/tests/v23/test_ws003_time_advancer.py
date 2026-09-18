"""WS-003：TimeAdvancer 与 life_loop world_simulation 维护步测试。"""

from datetime import datetime, timedelta

import pytest

from app.application import world_engine
from app.core.settings import get_settings
from app.repositories import world_repository
from app.services.world.time_advancer import TimeAdvanceResult, advance_world_time


def _flags_on(monkeypatch, **extra):
    for key, value in extra.items():
        monkeypatch.setenv(key.upper(), str(value).lower())
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def sim_flags(monkeypatch):
    yield from _flags_on(monkeypatch, world_time_mode="simulated")


@pytest.fixture
def real_flags(monkeypatch):
    yield from _flags_on(monkeypatch, world_time_mode="real_sync")


@pytest.fixture
def story_flags(monkeypatch):
    yield from _flags_on(monkeypatch, world_time_mode="story")


def _make_world(user_id: str, **overrides):
    world = world_repository.ensure_world(user_id)
    for key, value in overrides.items():
        setattr(world, key, value)
    world_repository.save_world(world)
    return world_repository.get_world(user_id)


def test_first_advance_only_sets_anchor(db_session_factory, sim_flags):
    user = "ws003-first"
    _make_world(user)
    now = datetime(2026, 9, 14, 10, 0)
    result = advance_world_time(user, now)
    assert result.mode == "simulated"
    assert result.advanced_minutes == 0.0
    assert result.truncated is False
    stored = world_repository.get_world(user)
    assert stored.sim_last_advanced_at == now
    assert stored.sim_time is None


def test_simulated_advance_scales_by_rate(db_session_factory, sim_flags):
    user = "ws003-scale"
    anchor = datetime(2026, 9, 14, 10, 0)
    _make_world(user, sim_time=anchor, sim_last_advanced_at=anchor, sim_rate=2.0)
    result = advance_world_time(user, anchor + timedelta(minutes=5))
    assert result.advanced_minutes == pytest.approx(10.0)
    stored = world_repository.get_world(user)
    assert stored.sim_time == anchor + timedelta(minutes=10)
    assert stored.sim_last_advanced_at == anchor + timedelta(minutes=5)


def test_simulated_advance_truncated_by_cap(db_session_factory, sim_flags):
    user = "ws003-cap"
    anchor = datetime(2026, 9, 14, 10, 0)
    _make_world(user, sim_time=anchor, sim_last_advanced_at=anchor, sim_rate=1.0)
    result = advance_world_time(user, anchor + timedelta(hours=8))
    assert result.truncated is True
    assert result.advanced_minutes == pytest.approx(sim_flags.sim_advance_max_minutes)
    assert world_repository.get_world(user).sim_last_advanced_at == anchor + timedelta(hours=8)


def test_simulated_clock_regression_advances_zero(db_session_factory, sim_flags):
    user = "ws003-back"
    anchor = datetime(2026, 9, 14, 10, 0)
    _make_world(user, sim_time=anchor, sim_last_advanced_at=anchor)
    result = advance_world_time(user, anchor - timedelta(minutes=30))
    assert result.advanced_minutes == 0.0
    assert world_repository.get_world(user).sim_time == anchor


def test_real_sync_never_touches_sim_time(db_session_factory, real_flags):
    user = "ws003-real"
    sim_time = datetime(2026, 9, 14, 9, 0)
    _make_world(user, sim_time=sim_time)
    now = datetime(2026, 9, 14, 18, 0)
    result = advance_world_time(user, now)
    assert result.mode == "real_sync"
    assert result.advanced_minutes == 0.0
    stored = world_repository.get_world(user)
    assert stored.sim_time == sim_time
    assert stored.sim_last_advanced_at == now


def test_story_mode_never_advances(db_session_factory, story_flags):
    user = "ws003-story"
    sim_time = datetime(2026, 9, 14, 9, 0)
    _make_world(user, sim_time=sim_time, sim_last_advanced_at=sim_time)
    now = datetime(2026, 9, 14, 20, 0)
    result = advance_world_time(user, now)
    assert result.mode == "story"
    stored = world_repository.get_world(user)
    assert stored.sim_time == sim_time
    assert stored.sim_last_advanced_at == now


def test_maintenance_step_ensures_world_when_missing(db_session_factory):
    world_engine.run_simulation_maintenance("ws003-off")
    assert world_repository.get_world("ws003-off") is not None


def test_maintenance_step_runs_for_all_worlds(db_session_factory, sim_flags):
    user = "ws003-all"
    _make_world(user)
    now = datetime(2026, 9, 14, 12, 0)
    results = world_engine.run_simulation_maintenance(now=now)
    assert any(r.anchor == now for r in results)
    assert world_repository.get_world(user).sim_last_advanced_at == now


def test_maintenance_step_runs_substeps(db_session_factory, sim_flags, monkeypatch):
    calls = []
    from app.services.world import day_cycle

    def _substep(user_id, now=None):
        calls.append((user_id, now))

    monkeypatch.setattr(day_cycle, "emit_time_markers", _substep)
    world_engine.run_simulation_maintenance("ws003-hook", now=datetime(2026, 9, 14, 12, 0))
    assert calls and calls[0][0] == "ws003-hook"


def test_advance_failure_degrades_to_none(monkeypatch, db_session_factory, sim_flags):
    from app.repositories import world_simulation_repository as repo

    def _explode(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "commit_time_advance", _explode)
    assert advance_world_time("ws003-err", datetime(2026, 9, 14, 12, 0)) is None


def test_result_shape():
    now = datetime(2026, 9, 14, 12, 0)
    result = TimeAdvanceResult(mode="simulated", advanced_minutes=1.0, truncated=False, anchor=now)
    assert result.advanced_minutes == 1.0
