"""V8-003 时间推进落库：simulated/story 持久化，real_sync no-op。"""

from datetime import datetime, timedelta

from app.application import world_engine
from app.character.asuna.world import OBJECT_STATE_MACHINES  # noqa: F401
from app.models.world import WorldTimeMode
from app.repositories import world_repository


def test_advance_time_persists_for_simulated(db_session_factory, override_settings):
    override_settings(world_time_mode="simulated", world_sim_rate=2.0)
    world = world_engine.ensure_world("default-user")
    assert world.time_mode is WorldTimeMode.SIMULATED
    delta = timedelta(hours=12)
    advanced = world_engine.advance_time("default-user", delta)
    assert advanced.sim_time is not None
    reloaded = world_engine.get_world("default-user")
    assert reloaded.sim_time == advanced.sim_time


def test_advance_time_noop_for_real_sync(db_session_factory):
    world = world_engine.ensure_world("default-user")
    assert world.time_mode is WorldTimeMode.REAL_SYNC
    unchanged = world_engine.advance_time("default-user", timedelta(days=1))
    assert unchanged.sim_time is None


def test_story_time_persists(db_session_factory, override_settings):
    override_settings(world_time_mode="story")
    world_engine.ensure_world("default-user")
    advanced = world_engine.advance_time("default-user", timedelta(days=2))
    assert advanced.sim_time is not None
    reloaded = world_engine.get_world("default-user")
    assert reloaded.time_mode is WorldTimeMode.STORY
    assert reloaded.sim_time is not None


def test_build_time_context(db_session_factory):
    context = world_engine.build_time_context(
        "default-user", provider=world_engine._default_provider
    )
    assert context is not None
    assert context.time_mode is WorldTimeMode.REAL_SYNC
    assert context.weekday in ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
    assert context.part_of_day in ("morning", "afternoon", "dusk", "evening", "late_night")
