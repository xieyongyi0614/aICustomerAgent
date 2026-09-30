"""API-008 简报合成：确定性装配，零 LLM；数据缺失逐卡降级或省略。

数据源现状：任务（`task_service`，真实）+ 天气（`services/weather`，现实源，
取不到降级为显式占位）。日程 / 健康 / 记忆暂无数据源，对应卡片**省略**——
宁可少一张卡，不展示假数据（v5.0.0 code review B-P1-3 的整改方向）。

天气定位优先级：请求携带坐标（端侧实时定位）> 用户偏好城市（落库，已地理编码）
> env 兜底坐标（`WEATHER_LATITUDE/LONGITUDE`）> 无（天气卡降级）。

响应契约字段（APP-018 §4.4 冻结）：`{type, greeting, title, orb_note, cards[], cta,
generated_at}`；端上只渲染，不拼装结论文案。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from app.core.settings import get_settings
from app.repositories import briefing_preference_repository
from app.services import weather
from app.services.life import tasks as task_service

logger = logging.getLogger(__name__)

_MORNING = "morning"

_EVENING = "evening"

_GREETING_LABELS = {_MORNING: "早间简报", _EVENING: "晚间总结"}

_HEADLINES = {
    _MORNING: "早上好，今天交给我吧",
    _EVENING: "晚上好，今天也辛苦了",
}

_ORB_FALLBACKS = {_MORNING: "天气转凉，记得加件外套", _EVENING: "明天的节奏我已经帮你排好了"}

_CTAS = {_MORNING: "开始今天", _EVENING: "安顿明天"}


@dataclass(frozen=True)
class BriefCardDraft:
    title: str
    body: str
    note: str | None = None


@dataclass(frozen=True)
class BriefDraft:
    type: str
    greeting: str
    title: str
    orb_note: str
    cards: tuple[BriefCardDraft, ...]
    cta: str
    generated_at: str


async def compose_brief(
    form: str,
    user_id: str,
    latitude: float | None = None,
    longitude: float | None = None,
) -> BriefDraft:
    prefs = await asyncio.to_thread(briefing_preference_repository.get, user_id)
    if form == _MORNING:
        return await _compose_morning(user_id, prefs, latitude, longitude)
    return await _compose_evening(user_id, prefs)


def _greeting(prefs: briefing_preference_repository.BriefingPreferenceRow | None, form: str) -> str:
    settings = get_settings()
    saved = None
    if prefs is not None:
        saved = prefs.morning_at if form == _MORNING else prefs.evening_at
    fallback = (
        getattr(settings, "briefing_morning_time", "")
        if form == _MORNING
        else getattr(settings, "briefing_evening_time", "")
    )
    time = (saved or fallback or "").strip()
    label = _GREETING_LABELS[form]
    return f"{time} · {label}" if time else label


async def _compose_evening(
    user_id: str, prefs: briefing_preference_repository.BriefingPreferenceRow | None
) -> BriefDraft:
    open_count = await _open_task_count(user_id)
    return BriefDraft(
        type=_EVENING,
        greeting=_greeting(prefs, _EVENING),
        title=_HEADLINES[_EVENING],
        orb_note=_ORB_FALLBACKS[_EVENING],
        cards=(_unfinished_card(open_count),),
        cta=_CTAS[_EVENING],
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )


async def _compose_morning(
    user_id: str,
    prefs: briefing_preference_repository.BriefingPreferenceRow | None,
    latitude: float | None,
    longitude: float | None,
) -> BriefDraft:
    open_count, snapshot = await asyncio.gather(
        _open_task_count(user_id),
        _current_weather(prefs, latitude, longitude),
    )
    return BriefDraft(
        type=_MORNING,
        greeting=_greeting(prefs, _MORNING),
        title=_HEADLINES[_MORNING],
        orb_note=_morning_orb_note(snapshot),
        cards=(_weather_card(snapshot), _morning_task_card(open_count)),
        cta=_CTAS[_MORNING],
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )


async def _current_weather(
    prefs: briefing_preference_repository.BriefingPreferenceRow | None,
    latitude: float | None,
    longitude: float | None,
) -> weather.WeatherSnapshot | None:
    location = _resolve_location(prefs, latitude, longitude)
    if location is None:
        return None
    return await weather.get_current_weather(*location)


def _resolve_location(
    prefs: briefing_preference_repository.BriefingPreferenceRow | None,
    latitude: float | None,
    longitude: float | None,
) -> tuple[float, float] | None:
    if latitude is not None and longitude is not None:
        return (latitude, longitude)
    if (
        prefs is not None
        and prefs.latitude is not None
        and prefs.longitude is not None
    ):
        return (prefs.latitude, prefs.longitude)
    settings = get_settings()
    if settings.weather_latitude is not None and settings.weather_longitude is not None:
        return (settings.weather_latitude, settings.weather_longitude)
    return None


def _morning_orb_note(snapshot: weather.WeatherSnapshot | None) -> str:
    if snapshot is None:
        return _ORB_FALLBACKS[_MORNING]
    return f"今天{snapshot.condition}，{snapshot.temperature_c:.0f}°"


def _weather_card(snapshot: weather.WeatherSnapshot | None) -> BriefCardDraft:
    if snapshot is None:
        return BriefCardDraft(
            title="天气",
            body="暂无实时数据",
            note="天气源未配置或暂不可用",
        )
    details: list[str] = []
    if snapshot.temp_min_c is not None and snapshot.temp_max_c is not None:
        details.append(f"今日 {snapshot.temp_min_c:.0f}°~{snapshot.temp_max_c:.0f}°")
    if snapshot.precipitation_probability is not None:
        details.append(f"降水 {snapshot.precipitation_probability}%")
    return BriefCardDraft(
        title="天气",
        body=f"{snapshot.temperature_c:.0f}° {snapshot.condition}",
        note=" · ".join(details) or None,
    )


def _morning_task_card(open_count: int) -> BriefCardDraft:
    if open_count:
        return BriefCardDraft(
            title="任务",
            body=f"{open_count} 项 · 已按你的节奏排好",
            note="先从压力最小的一件开始",
        )
    return BriefCardDraft(title="任务", body="0 项", note="今天还很轻松")


def _unfinished_card(open_count: int) -> BriefCardDraft:
    return BriefCardDraft(
        title="未完成",
        body=f"{open_count} 项已重新排期",
        note="不用赶，明天接着来",
    )


async def _open_task_count(user_id: str) -> int:
    if not user_id:
        return 0
    try:
        tasks = await asyncio.to_thread(task_service.list_open, user_id)
    except Exception as error:
        logger.warning(
            "简报任务数读取失败，按 0 处理: %s: %s",
            error.__class__.__name__,
            error,
        )
        return 0
    return len(tasks)
