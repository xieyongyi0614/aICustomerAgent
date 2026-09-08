"""Settings 领域共享常量与异常。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(Exception):
    pass


_OBSERVABILITY_PROMPT_MODES = ("disabled", "sampled", "always")

STAGE_KEYS = ("stranger", "friend", "close_friend", "partner")

DOMAIN_MODEL_CONFIG = SettingsConfigDict(
    env_file=".env", env_file_encoding="utf-8", extra="ignore"
)
