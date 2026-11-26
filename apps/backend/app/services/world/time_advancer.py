"""V2.3.0 TimeAdvancer（architecture.md §5.2）：世界时间自主推进。

real_sync 直读真实钟仅落锚点；simulated 按真实流逝 × sim_rate 推进（单次上限
防补帧风暴）；story 不自动推进。锚点与 sim_time 同事务落库，回拨按 0 推进。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import timeutil
from app.core.settings import get_settings
from app.models.world import World, WorldTimeMode
from app.repositories import world_repository, world_simulation_repository

logger = logging.getLogger(__name__)


@dataclass
class TimeAdvanceResult:
    mode: str
    advanced_minutes: float
    truncated: bool
    anchor: datetime


def _advance_simulated(world: World, now: datetime) -> TimeAdvanceResult:
    settings = get_settings()
    anchor = world.sim_last_advanced_at
    if anchor is None:
        world_simulation_repository.commit_time_advance(world.world_id, world.sim_time, now)
        return TimeAdvanceResult(
            mode=world.time_mode.value, advanced_minutes=0.0, truncated=False, anchor=now
        )
    real_delta_seconds = (now - anchor).total_seconds()
    if real_delta_seconds <= 0:
        return TimeAdvanceResult(
            mode=world.time_mode.value, advanced_minutes=0.0, truncated=False, anchor=now
        )
    sim_delta_seconds = real_delta_seconds * world.sim_rate
    max_seconds = settings.sim_advance_max_minutes * 60
    truncated = sim_delta_seconds > max_seconds
    if truncated:
        sim_delta_seconds = max_seconds
    advanced_minutes = sim_delta_seconds / 60.0
    new_sim_time = (world.sim_time or anchor) + timedelta(seconds=sim_delta_seconds)
    world_simulation_repository.commit_time_advance(world.world_id, new_sim_time, now)
    return TimeAdvanceResult(
        mode=world.time_mode.value,
        advanced_minutes=advanced_minutes,
        truncated=truncated,
        anchor=now,
    )


def advance_world_time(user_id: str, now: datetime | None = None) -> TimeAdvanceResult | None:
    try:
        world = world_repository.ensure_world(user_id)
        if world is None:
            return None
        current = timeutil.ensure_aware(now) or timeutil.now()
        if world.time_mode is WorldTimeMode.SIMULATED:
            return _advance_simulated(world, current)
        world_simulation_repository.commit_time_advance(world.world_id, world.sim_time, current)
        return TimeAdvanceResult(
            mode=world.time_mode.value, advanced_minutes=0.0, truncated=False, anchor=current
        )
    except Exception:
        logger.exception("世界时间推进失败")
        return None
