"""API-008 简报合成：确定性装配，零 LLM；数据缺失逐卡降级或省略。

数据源现状：任务（`task_service`，真实）+ 天气（`services/weather`，现实源，
取不到降级为显式占位）。日程 / 健康 / 记忆暂无数据源，对应卡片**省略**——
宁可少一张卡，不展示假数据（v5.0.0 code review B-P1-3 的整改方向）。

天气定位优先级：用户偏好城市（落库，已地理编码；显式选择压过环境感知）>
请求携带坐标（端侧实时定位）> 默认北京（零配置兜底，2026-10-07 用户裁决）。

响应契约字段（APP-018 §4.4 冻结）：`{type, greeting, title, orb_note, cards[], cta,
generated_at}`；端上只渲染，不拼装结论文案。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.core import timeutil
from app.core.settings import get_settings
from app.repositories import briefing_preference_repository
from app.services.briefing import weather
from app.services.car import service as car_service
from app.services.ledger import query as ledger_query
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

_DEFAULT_LOCATION = (39.9042, 116.4073)  # 北京：无偏好且无请求坐标时的零配置兜底

_LAT_RANGE = (-90.0, 90.0)

_LON_RANGE = (-180.0, 180.0)


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


def check_coord_pair(latitude: float | None, longitude: float | None) -> str | None:
    """请求坐标成对性与范围校验；合法返回 None，否则返回可直出的 422 文案。"""
    if (latitude is None) != (longitude is None):
        return "lat 与 lon 必须成对提供"
    if latitude is not None and not _LAT_RANGE[0] <= latitude <= _LAT_RANGE[1]:
        return "lat 超出合法范围"
    if longitude is not None and not _LON_RANGE[0] <= longitude <= _LON_RANGE[1]:
        return "lon 超出合法范围"
    return None


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
        generated_at=timeutil.now().isoformat(timespec="seconds"),
    )


async def _compose_morning(
    user_id: str,
    prefs: briefing_preference_repository.BriefingPreferenceRow | None,
    latitude: float | None,
    longitude: float | None,
) -> BriefDraft:
    open_count, snapshot, spend, car = await asyncio.gather(
        _open_task_count(user_id),
        _current_weather(prefs, latitude, longitude),
        _spend_card(user_id),
        _car_card(user_id),
    )
    cards = [_weather_card(snapshot), _morning_task_card(open_count)]
    if car is not None:
        cards.append(car)
    if spend is not None:
        cards.append(spend)
    return BriefDraft(
        type=_MORNING,
        greeting=_greeting(prefs, _MORNING),
        title=_HEADLINES[_MORNING],
        orb_note=_morning_orb_note(snapshot),
        cards=tuple(cards),
        cta=_CTAS[_MORNING],
        generated_at=timeutil.now().isoformat(timespec="seconds"),
    )


async def _current_weather(
    prefs: briefing_preference_repository.BriefingPreferenceRow | None,
    latitude: float | None,
    longitude: float | None,
) -> weather.WeatherSnapshot | None:
    return await weather.get_current_weather(
        *_resolve_location(prefs, latitude, longitude)
    )


async def current_weather_for_user(
    user_id: str,
    latitude: float | None = None,
    longitude: float | None = None,
) -> weather.WeatherSnapshot | None:
    """首页总结兜底复用定位链取当前天气；偏好读取失败视为无偏好。

    取数失败由 `get_current_weather` 返回 None，调用方逐项降级。
    """
    try:
        prefs = await asyncio.to_thread(briefing_preference_repository.get, user_id)
    except Exception as error:
        logger.warning(
            "简报偏好读取失败，天气定位降级: %s: %s",
            error.__class__.__name__,
            error,
        )
        prefs = None
    return await weather.get_current_weather(
        *_resolve_location(prefs, latitude, longitude)
    )


def _resolve_location(
    prefs: briefing_preference_repository.BriefingPreferenceRow | None,
    latitude: float | None,
    longitude: float | None,
) -> tuple[float, float]:
    """定位链：显式偏好城市压过环境感知（请求坐标），末位默认北京。"""
    if (
        prefs is not None
        and prefs.latitude is not None
        and prefs.longitude is not None
    ):
        return (prefs.latitude, prefs.longitude)
    if latitude is not None and longitude is not None:
        return (latitude, longitude)
    return _DEFAULT_LOCATION


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


_SPEND_WINDOW_DAYS = 7


def _spend_window() -> tuple[datetime, datetime]:
    """近 7 天（含今天，本地日边界）——与首页 `/home/summary` 同口径。"""
    today = timeutil.local_now().date()
    since = datetime.combine(
        today - timedelta(days=_SPEND_WINDOW_DAYS - 1),
        time.min,
        tzinfo=timeutil.LOCAL_TZ,
    )
    return since, since + timedelta(days=_SPEND_WINDOW_DAYS)


async def _spend_card(user_id: str) -> BriefCardDraft | None:
    """近 7 天消费卡：账本真实汇总，无记账省卡（逐卡降级纪律）。"""
    try:
        since, until = _spend_window()
        week = await asyncio.to_thread(
            ledger_query.summary,
            user_id,
            period=ledger_query.Period.custom(since, until, label="week"),
            compare_previous=True,
        )
    except Exception as error:
        logger.warning(
            "简报消费读取失败，消费卡省略: %s: %s",
            error.__class__.__name__,
            error,
        )
        return None
    if not week.entry_count:
        return None
    spent = abs(week.expense_minor) / 100
    note: str | None = None
    compared = week.compared_to_previous
    ratio = compared.expense_ratio if compared is not None else None
    if ratio is not None:
        note = (
            f"比上周少 {abs(ratio) * 100:.0f}%"
            if ratio < 0
            else f"比上周多 {ratio * 100:.0f}%"
        )
    return BriefCardDraft(
        title="消费",
        body=f"近 {_SPEND_WINDOW_DAYS} 天 ¥{spent:.0f} · {week.entry_count} 笔",
        note=note,
    )


async def _car_card(user_id: str) -> BriefCardDraft | None:
    """车辆临期提醒卡：只收 soon 级（临近/已到保养、保险、年检），无事省卡。"""
    try:
        items = await asyncio.to_thread(car_service.reminders, user_id)
    except Exception as error:
        logger.warning(
            "简报车辆提醒读取失败，车辆卡省略: %s: %s",
            error.__class__.__name__,
            error,
        )
        return None
    soon = [item for item in items if item.level == "soon"]
    if not soon:
        return None
    body = "\n".join(f"{item.title} {item.detail}" for item in soon)
    return BriefCardDraft(title="车辆", body=body)


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
