"""V2.3.0 WeatherEvolver（architecture.md §5.2）：确定性天气演化。

种子 = (world_id, date)，同日同世界重放结果一致（G6）；
天气词表沿用角色资产 WORLD_WEATHER_VALUES。
"""

import logging
import random
from datetime import date

from app.core import timeutil
from app.character.asuna.calendar import season_of
from app.character.asuna.world import WORLD_WEATHER_VALUES

logger = logging.getLogger(__name__)

BASELINE_WEATHER = {
    "spring": "sunny",
    "summer": "sunny",
    "autumn": "cloudy",
    "winter": "cloudy",
}

TEMPERATURE_BAND = {
    "spring": (12.0, 22.0),
    "summer": (24.0, 34.0),
    "autumn": (10.0, 20.0),
    "winter": (-2.0, 8.0),
}

TEMPERATURE_ADJUST = {
    "sunny": 2.0,
    "cloudy": 0.0,
    "rain": -2.0,
    "snow": -4.0,
    "windy": -1.0,
}

_TRANSITIONS: dict[str, dict[str, list[tuple[str, int]]]] = {
    "spring": {
        "sunny": [("sunny", 5), ("cloudy", 3), ("rain", 2)],
        "cloudy": [("cloudy", 4), ("sunny", 3), ("rain", 3)],
        "rain": [("cloudy", 5), ("rain", 3), ("sunny", 2)],
        "windy": [("cloudy", 4), ("sunny", 4), ("windy", 2)],
    },
    "summer": {
        "sunny": [("sunny", 7), ("cloudy", 2), ("rain", 1)],
        "cloudy": [("sunny", 4), ("cloudy", 3), ("rain", 3)],
        "rain": [("cloudy", 4), ("rain", 3), ("sunny", 3)],
        "windy": [("sunny", 5), ("cloudy", 5)],
    },
    "autumn": {
        "sunny": [("sunny", 4), ("cloudy", 4), ("rain", 1), ("windy", 1)],
        "cloudy": [("cloudy", 5), ("rain", 3), ("sunny", 2)],
        "rain": [("cloudy", 5), ("rain", 4), ("windy", 1)],
        "windy": [("cloudy", 5), ("rain", 3), ("windy", 2)],
    },
    "winter": {
        "sunny": [("sunny", 4), ("cloudy", 5), ("windy", 1)],
        "cloudy": [("cloudy", 5), ("snow", 2), ("sunny", 2), ("windy", 1)],
        "rain": [("cloudy", 5), ("snow", 3), ("rain", 2)],
        "snow": [("cloudy", 4), ("snow", 4), ("sunny", 2)],
        "windy": [("cloudy", 5), ("snow", 3), ("windy", 2)],
    },
}

SIGNIFICANT_WEATHER = ("rain", "snow", "windy")


def evolve(prev_weather: str | None, season: str, day: date, world_id: str) -> tuple[str, float]:
    """返回 (次日天气, 气温)；确定性：同 (world_id, day) 恒定。"""
    rng = random.Random(f"{world_id}|{day.isoformat()}")
    base = prev_weather if prev_weather in WORLD_WEATHER_VALUES else BASELINE_WEATHER.get(season, "sunny")
    table = _TRANSITIONS.get(season, {}).get(base)
    if not table:
        next_weather = BASELINE_WEATHER.get(season, "sunny")
    else:
        total = sum(weight for _, weight in table)
        pick = rng.uniform(0, total)
        cursor = 0.0
        next_weather = table[-1][0]
        for candidate, weight in table:
            cursor += weight
            if pick <= cursor:
                next_weather = candidate
                break
    low, high = TEMPERATURE_BAND.get(season, (10.0, 20.0))
    temperature = round(
        rng.uniform(low, high) + TEMPERATURE_ADJUST.get(next_weather, 0.0), 1
    )
    return next_weather, temperature


def importance_for(prev_weather: str | None, next_weather: str) -> str:
    if next_weather in SIGNIFICANT_WEATHER and next_weather != prev_weather:
        return "normal"
    if prev_weather is not None and prev_weather != next_weather:
        return "low"
    return "low"


def evolve_daily_weather(user_id: str) -> str | None:
    """编排：每日演化一次天气并落事件；幂等键 weather:{date}。"""
    from app.services.world import engine_port as world_engine
    from app.repositories import world_repository, world_simulation_repository

    try:
        world = world_repository.get_world(user_id)
        if world is None:
            return None
        ctx = world_engine._default_provider.context(world)
        day = timeutil.local(ctx.now).date()
        key = f"weather:{day.isoformat()}"
        if key in world_simulation_repository.get_latest_idempotency_keys(
            world.world_id, [key]
        ):
            return None
        season = season_of(day)
        prev = world.environment.weather
        next_weather, temperature = evolve(prev, season, day, world.world_id)
        world_engine.set_environment(
            user_id,
            updated_by="weather_sim",
            weather=next_weather,
            temperature_c=temperature,
        )
        created = world_engine.create_event(
            user_id,
            event_type="weather_change",
            title=f"天气转为{next_weather}",
            importance=importance_for(prev, next_weather),
            source="weather",
            status="completed",
            payload={
                "prev": prev,
                "next": next_weather,
                "season": season,
                "date": day.isoformat(),
                "changed": prev != next_weather,
                "temperature_c": temperature,
            },
            idempotency_key=key,
        )
        return key if created is not None else None
    except Exception:
        logger.exception("天气演化失败")
        return None
