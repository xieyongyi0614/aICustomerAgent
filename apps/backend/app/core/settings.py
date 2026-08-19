from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(Exception):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    base_url: str = "https://api.longcat.chat/openai/v1"
    model: str = "LongCat-2.0"
    temperature: float = 0.9
    top_p: float = 0.92
    frequency_penalty: float = 0.4
    presence_penalty: float = 0.5
    max_tokens: int = 50
    extra_body_thinking: str = "disabled"

    database_url: str = "sqlite:///./asuna.db"

    summary_threshold: int = 40
    memory_importance_threshold: float = 0.6
    memory_top_k: int = 5
    conversation_max_messages: int = 20
    conversation_max_chars: int = 8000

    @model_validator(mode="after")
    def validate_api_key(self):
        if not self.openai_api_key:
            raise SettingsError("请在 .env 配置 OPENAI_API_KEY")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
