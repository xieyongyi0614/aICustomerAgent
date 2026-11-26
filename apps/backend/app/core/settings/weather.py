"""天气域设置：简报天气卡的现实天气源（Open-Meteo）参数；定位零 env 配置。

定位由 `services/briefing/compose` 的定位链解析（偏好城市 > 请求坐标 >
默认北京），不再提供 env 兜底坐标（2026-10-07 用户裁决）。
"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class WeatherSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    weather_api_base_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_cache_ttl_seconds: int = 1800
    weather_request_timeout_seconds: float = 3.0
    weather_geocode_base_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    weather_geocode_language: str = "zh"

    @model_validator(mode="after")
    def _validate_weather_domain(self):
        if self.weather_cache_ttl_seconds < 0:
            raise SettingsError("WEATHER_CACHE_TTL_SECONDS 不得为负")
        if self.weather_request_timeout_seconds <= 0:
            raise SettingsError("WEATHER_REQUEST_TIMEOUT_SECONDS 必须大于 0")
        return self
