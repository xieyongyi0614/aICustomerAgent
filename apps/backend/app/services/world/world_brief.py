"""V2.3.0 WorldBriefAssembler（architecture.md §5.1）：世界"此刻状态"简报。

纯函数装配；输入缺失逐段降级；text ≤ world_brief_char_budget。
"""

import logging

from app.models.world import TimeContext, World
from app.models.world_simulation import UserSituation, WorldBrief

logger = logging.getLogger(__name__)

PART_OF_DAY_CN = {
    "morning": "上午",
    "afternoon": "中午",
    "dusk": "下午",
    "evening": "晚上",
    "late_night": "深夜",
}

WEATHER_CN = {
    "sunny": "晴天",
    "cloudy": "多云",
    "rain": "雨天",
    "snow": "雪天",
    "windy": "有风",
}


def _time_line(time_ctx: TimeContext, weather: str | None) -> str:
    from app.models.world import WEEKDAY_CN

    clock = time_ctx.now.strftime("%H:%M")
    part = PART_OF_DAY_CN.get(time_ctx.part_of_day, "")
    date_text = time_ctx.now.strftime("%m-%d")
    weather_text = WEATHER_CN.get(weather or "", "")
    segments = [date_text, WEEKDAY_CN[time_ctx.now.weekday()], part, clock]
    if weather_text:
        segments.append(weather_text)
    return " ".join(s for s in segments if s)


def _place_line(world: World, block) -> str:
    from app.services.world.locations import location_name

    place = location_name(world.current_location) or world.current_location
    if block is not None:
        return f"她此刻在{place}，正在{block.activity}。"
    return f"她此刻在{place}。"


def _situations_line(situations: list[UserSituation] | None) -> str | None:
    if not situations:
        return None
    top = situations[0]
    return f"用户{top.summary.replace('用户', '', 1)}（{top.intensity}/5）"


def _events_line(salient_events: list) -> str | None:
    titles = [getattr(event, "title", "") for event in (salient_events or [])][:2]
    titles = [t for t in titles if t]
    if not titles:
        return None
    return "最近：" + "；".join(titles)


def build_world_brief(
    time_ctx: TimeContext,
    world: World,
    block=None,
    situations: list[UserSituation] | None = None,
    salient_events: list | None = None,
    budget: int = 400,
) -> WorldBrief:
    try:
        time_line = _time_line(time_ctx, world.environment.weather)
        place_line = _place_line(world, block)
        situations_line = _situations_line(situations)
        events_line = _events_line(salient_events)

        segments: list[str] = [time_line, place_line]
        for extra in (situations_line, events_line):
            if extra is not None:
                segments.append(extra)
        text = "。".join(s.rstrip("。") for s in segments) + "。"
        if len(text) > budget and events_line is not None:
            segments = [s for s in segments if s != events_line]
            text = "。".join(s.rstrip("。") for s in segments) + "。"
        if len(text) > budget and situations_line is not None:
            segments = [s for s in segments if s != situations_line]
            text = "。".join(s.rstrip("。") for s in segments) + "。"
        if len(text) > budget:
            text = text[:budget]
        return WorldBrief(
            text=text,
            time_line=time_line,
            place_line=place_line,
            situations_line=situations_line,
            events_line=events_line,
        )
    except Exception:
        logger.exception("世界简报装配失败")
        return WorldBrief(text="")
