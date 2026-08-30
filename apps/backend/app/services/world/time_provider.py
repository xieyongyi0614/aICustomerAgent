"""V8 TimeProvider（time-system.md §2）：world 域唯一时间读取口。

real_sync 直读真实时钟；simulated/story 的世界时钟存于 worlds.sim_time，
仅经 advance 显式推进（simulated 按 rate 缩放，story 原样步进）。
real_now 可注入用于测试时间冻结。不接管 Runtime 既有的 datetime.now() 消费者。
"""

from datetime import datetime, timedelta

from app.models.world import TimeContext, WEEKDAY_CN, World, WorldTimeMode, part_of_day


class TimeProvider:
    def __init__(self, real_now=None) -> None:
        self._real_now = real_now or datetime.now

    def now(self, world: World) -> datetime:
        if world.time_mode is WorldTimeMode.REAL_SYNC:
            return self._real_now()
        return world.sim_time or self._real_now()

    def context(self, world: World) -> TimeContext:
        now = self.now(world)
        return TimeContext(
            now=now,
            weekday=WEEKDAY_CN[now.weekday()],
            part_of_day=part_of_day(now),
            time_mode=world.time_mode,
            note=None,
        )

    def advance(self, world: World, delta: timedelta) -> World:
        base = world.sim_time or self._real_now()
        if world.time_mode is WorldTimeMode.SIMULATED:
            world.sim_time = base + delta * world.sim_rate
        else:
            world.sim_time = base + delta
        return world
