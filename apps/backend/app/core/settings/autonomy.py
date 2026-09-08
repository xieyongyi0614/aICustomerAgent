"""主动行为域设置（V7 Autonomy）：tick 节奏、静默时段、重试与退避。"""

import re as _re

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class AutonomySettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    autonomy_enabled: bool = True
    autonomy_tick_seconds: int = 60
    autonomy_inactivity_minutes: int = 30
    autonomy_min_interval_minutes: int = 240
    autonomy_min_interval_floor_minutes: int = 60
    autonomy_max_attempts_per_episode: int = 2
    autonomy_backoff_multiplier: float = 2.0
    autonomy_quiet_hours_start: str = "23:00"
    autonomy_quiet_hours_end: str = "08:00"
    autonomy_max_retries: int = 2
    autonomy_poll_seconds: int = 30
    autonomy_min_user_reply_gap_minutes: int = 2

    @model_validator(mode="after")
    def validate_autonomy_quiet_hours(self):
        pattern = _re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
        for name in ("autonomy_quiet_hours_start", "autonomy_quiet_hours_end"):
            value = getattr(self, name)
            if not pattern.match(value):
                raise SettingsError(f"{name} 必须是 HH:MM 格式: {value}")
        return self
