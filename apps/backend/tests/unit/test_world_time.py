"""V8-003 TimeProvider：real_sync / simulated / story 三模式（time-system.md §1~§2）。"""

from datetime import datetime, timedelta

from app.core import timeutil
from app.models.world import World, WorldTimeMode
from app.services.world.time_provider import TimeProvider

FROZEN = timeutil.ensure_aware(datetime(2026, 8, 31, 23, 40))


def _world(mode, sim_time=None, rate=1.0):
    return World(
        world_id="home:default-user",
        user_id="default-user",
        time_mode=mode,
        sim_time=sim_time,
        sim_rate=rate,
    )


def test_real_sync_reads_injected_clock():
    provider = TimeProvider(real_now=lambda: FROZEN)
    world = _world(WorldTimeMode.REAL_SYNC)
    assert provider.now(world) == FROZEN
    context = provider.context(world)
    assert context.part_of_day == "late_night"
    assert context.time_mode is WorldTimeMode.REAL_SYNC
    assert world.sim_time is None


def test_simulated_advance_scales_by_rate():
    provider = TimeProvider(real_now=lambda: FROZEN)
    world = _world(WorldTimeMode.SIMULATED, sim_time=FROZEN, rate=2.0)
    advanced = provider.advance(world, timedelta(hours=1))
    assert advanced.sim_time == FROZEN + timedelta(hours=2)
    assert provider.now(advanced) == FROZEN + timedelta(hours=2)


def test_story_advance_steps_exactly():
    provider = TimeProvider(real_now=lambda: FROZEN)
    world = _world(WorldTimeMode.STORY)
    advanced = provider.advance(world, timedelta(days=3))
    assert advanced.sim_time == FROZEN + timedelta(days=3)


def test_simulated_without_sim_time_falls_back_to_real_now():
    provider = TimeProvider(real_now=lambda: FROZEN)
    world = _world(WorldTimeMode.SIMULATED)
    assert provider.now(world) == FROZEN
