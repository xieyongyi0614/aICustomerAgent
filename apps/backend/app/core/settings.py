from functools import lru_cache

import json

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(Exception):
    pass


class LlmProfile:
    def __init__(
        self,
        id: str,
        label: str,
        base_url: str,
        model: str,
        api_key: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        frequency_penalty: float,
        presence_penalty: float,
        extra_body_thinking: str,
        default: bool = False,
    ):
        self.id = id
        self.label = label
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.extra_body_thinking = extra_body_thinking
        self.default = default

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "model": self.model,
            "default": self.default,
        }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_profiles_json: str = ""
    default_llm_profile: str = "longcat"
    temperature: float = 0.9
    top_p: float = 0.92
    frequency_penalty: float = 0.4
    presence_penalty: float = 0.5
    max_tokens: int = 50
    extra_body_thinking: str = "disabled"

    database_url: str = "postgresql+psycopg://asuna:asuna@localhost:5432/asuna"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True

    summary_threshold: int = 40
    router_confidence_threshold: float = 0.5
    memory_importance_threshold: float = 0.6
    memory_top_k: int = 5
    conversation_max_messages: int = 20
    conversation_max_chars: int = 8000

    energy_turn_decay: float = 0.05
    energy_min: float = 0.1
    energy_reset_hours: int = 12
    energy_reset_value: float = 0.85
    stage_friend_familiarity: float = 0.35
    stage_close_intimacy: float = 0.55
    stage_close_trust: float = 0.55
    stage_partner_intimacy: float = 0.75
    stage_partner_trust: float = 0.75
    stage_hysteresis: float = 0.10
    analysis_recent_messages: int = 6
    trace_capacity: int = 20
    state_history_limit: int = 20

    @model_validator(mode="after")
    def validate_profiles(self):
        if not self.llm_profiles_json:
            raise SettingsError("请在 .env 配置 LLM_PROFILES_JSON")
        try:
            parsed = json.loads(self.llm_profiles_json)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"LLM_PROFILES_JSON 解析失败: {exc}") from exc
        if not isinstance(parsed, list) or len(parsed) == 0:
            raise SettingsError("LLM_PROFILES_JSON 必须是非空数组")
        for item in parsed:
            if not isinstance(item, dict):
                raise SettingsError("LLM_PROFILES_JSON 每项必须是对象")
            for key in ("id", "label", "base_url", "model", "api_key"):
                if not item.get(key):
                    raise SettingsError(f"LLM_PROFILES_JSON 缺少字段: {key}")
        ids = [item["id"] for item in parsed]
        if len(set(ids)) != len(ids):
            raise SettingsError("LLM_PROFILES_JSON id 不可重复")
        if self.default_llm_profile not in ids:
            raise SettingsError(
                f"DEFAULT_LLM_PROFILE 必须在 LLM_PROFILES_JSON 中: {self.default_llm_profile}"
            )
        return self

    def llm_profiles(self) -> list[LlmProfile]:
        raw = json.loads(self.llm_profiles_json)
        profiles: list[LlmProfile] = []
        for item in raw:
            profiles.append(
                LlmProfile(
                    id=item["id"],
                    label=item["label"],
                    base_url=item["base_url"],
                    model=item["model"],
                    api_key=item["api_key"],
                    max_tokens=int(item.get("max_tokens", self.max_tokens)),
                    temperature=float(item.get("temperature", self.temperature)),
                    top_p=float(item.get("top_p", self.top_p)),
                    frequency_penalty=float(item.get("frequency_penalty", self.frequency_penalty)),
                    presence_penalty=float(item.get("presence_penalty", self.presence_penalty)),
                    extra_body_thinking=str(
                        item.get("extra_body_thinking", self.extra_body_thinking)
                    ),
                    default=item["id"] == self.default_llm_profile,
                )
            )
        return profiles

    def get_llm_profile(self, profile_id: str | None) -> LlmProfile:
        profiles = self.llm_profiles()
        target = profile_id or self.default_llm_profile
        for profile in profiles:
            if profile.id == target:
                return profile
        raise SettingsError(f"未知 LLM profile: {target}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
