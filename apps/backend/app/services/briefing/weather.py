"""现实天气源（Open-Meteo）：简报天气卡的数据后端与城市地理编码。

与 `services/world/weather.py` 的**设定天气**（世界模拟，种子确定性演化）相对，本模块
取**现实天气**。坐标由调用方解析后传入（请求参数 / 用户偏好城市 / env 兜底），进程内
按坐标分键 TTL 缓存；网络失败 / 响应不合预期一律返回 None（fail-open，与入站去重同
取向：天气取不到不应让简报 500）。数据契约仅对 Open-Meteo v1（`weather_api_base_url`
/ `weather_geocode_base_url` 可指向同构替代源）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_WMO_CONDITIONS: dict[int, str] = {
    0: "晴",
    1: "晴",
    2: "少云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "毛毛雨",
    55: "毛毛雨",
    56: "冻毛毛雨",
    57: "冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "雷阵雨伴冰雹",
}

_UNKNOWN_CONDITION = "未知"

_CACHE_COORD_PRECISION = 2

_GEOCODE_CACHE_MAX_ENTRIES = 1000


@dataclass(frozen=True)
class WeatherSnapshot:
    temperature_c: float
    condition: str
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    precipitation_probability: int | None = None


@dataclass(frozen=True)
class GeoLocation:
    name: str
    latitude: float
    longitude: float


class WeatherTransport:
    """HTTP 接缝（默认 urllib + to_thread，与通道适配器同款倒置；测试注入替身）。"""

    async def fetch_json(self, url: str, timeout_seconds: float) -> Any:
        return await asyncio.to_thread(self._fetch_sync, url, timeout_seconds)

    def _fetch_sync(self, url: str, timeout_seconds: float) -> Any:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read())


def _first_number(raw: Any) -> float | int | None:
    if isinstance(raw, (list, tuple)) and raw:
        raw = raw[0]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return raw


def _parse(payload: Any) -> WeatherSnapshot | None:
    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        return None
    temperature = current.get("temperature_2m")
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        return None
    code = current.get("weather_code")
    daily = payload.get("daily") if isinstance(payload, dict) else None
    daily = daily if isinstance(daily, dict) else {}
    temp_min = _first_number(daily.get("temperature_2m_min"))
    temp_max = _first_number(daily.get("temperature_2m_max"))
    precip = _first_number(daily.get("precipitation_probability_max"))
    return WeatherSnapshot(
        temperature_c=float(temperature),
        condition=_WMO_CONDITIONS.get(code, _UNKNOWN_CONDITION)
        if isinstance(code, int)
        else _UNKNOWN_CONDITION,
        temp_min_c=float(temp_min) if temp_min is not None else None,
        temp_max_c=float(temp_max) if temp_max is not None else None,
        precipitation_probability=int(precip) if precip is not None else None,
    )


def _forecast_url(latitude: float, longitude: float, settings: Any) -> str:
    query = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 1,
            "timezone": "auto",
        }
    )
    return f"{settings.weather_api_base_url}?{query}"


def _geocode_url(city: str, settings: Any) -> str:
    query = urllib.parse.urlencode(
        {
            "name": city,
            "count": 1,
            "language": settings.weather_geocode_language,
            "format": "json",
        }
    )
    return f"{settings.weather_geocode_base_url}?{query}"


async def _fetch_forecast(
    latitude: float, longitude: float, settings: Any
) -> WeatherSnapshot | None:
    try:
        payload = await _transport().fetch_json(
            _forecast_url(latitude, longitude, settings),
            settings.weather_request_timeout_seconds,
        )
        snapshot = _parse(payload)
    except Exception as error:
        logger.warning(
            "天气取数失败，简报天气卡将降级: %s: %s",
            error.__class__.__name__,
            error,
        )
        return None
    if snapshot is None:
        logger.warning("天气响应缺少必要字段，简报天气卡将降级")
    return snapshot


async def get_current_weather(latitude: float, longitude: float) -> WeatherSnapshot | None:
    """当前天气快照；网络失败或响应不合预期返回 None（调用方逐卡降级）。"""
    settings = get_settings()
    key = (
        round(latitude, _CACHE_COORD_PRECISION),
        round(longitude, _CACHE_COORD_PRECISION),
    )
    now = time.monotonic()
    cached = _forecast_cache.get(key)
    if cached is not None and now - cached[1] < settings.weather_cache_ttl_seconds:
        return cached[0]
    snapshot = await _fetch_forecast(latitude, longitude, settings)
    if snapshot is not None:
        _forecast_cache[key] = (snapshot, now)
    return snapshot


async def geocode_city(city: str) -> GeoLocation | None:
    """城市名 → 坐标（Open-Meteo geocoding，取首个结果）；失败返回 None。"""
    normalized = city.strip()
    if not normalized:
        return None
    cache_key = normalized.casefold()
    cached = _geocode_cache.get(cache_key)
    if cached is not None:
        return cached
    settings = get_settings()
    try:
        payload = await _transport().fetch_json(
            _geocode_url(normalized, settings),
            settings.weather_request_timeout_seconds,
        )
    except Exception as error:
        logger.warning(
            "城市地理编码失败: %s: %s",
            error.__class__.__name__,
            error,
        )
        return None
    results = payload.get("results") if isinstance(payload, dict) else None
    first = results[0] if isinstance(results, list) and results else None
    latitude = first.get("latitude") if isinstance(first, dict) else None
    longitude = first.get("longitude") if isinstance(first, dict) else None
    if isinstance(latitude, bool) or not isinstance(latitude, (int, float)):
        return None
    if isinstance(longitude, bool) or not isinstance(longitude, (int, float)):
        return None
    location = GeoLocation(
        name=str(first.get("name") or normalized),
        latitude=float(latitude),
        longitude=float(longitude),
    )
    if len(_geocode_cache) >= _GEOCODE_CACHE_MAX_ENTRIES:
        _geocode_cache.clear()
    _geocode_cache[cache_key] = location
    return location


_transport_impl: WeatherTransport | None = None

_forecast_cache: dict[tuple[float, float], tuple[WeatherSnapshot, float]] = {}

_geocode_cache: dict[str, GeoLocation] = {}


def _transport() -> WeatherTransport:
    global _transport_impl
    if _transport_impl is None:
        _transport_impl = WeatherTransport()
    return _transport_impl


def set_weather_transport(transport: WeatherTransport | None) -> None:
    """测试接缝：注入传输替身；`None` 恢复默认 urllib 实现。"""
    global _transport_impl
    _transport_impl = transport


def reset_weather_cache() -> None:
    """测试与配置变更用：清空进程内缓存（天气 + 地理编码）。"""
    _forecast_cache.clear()
    _geocode_cache.clear()
