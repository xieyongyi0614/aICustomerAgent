"""LLM Profile 域设置：采样参数、profile 表与校验。"""

import json

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


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
        extra_body: dict | None = None,
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
        self.extra_body = extra_body

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "model": self.model,
            "default": self.default,
        }


class LlmSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    llm_profiles_json: str = ""
    default_llm_profile: str = "longcat"
    temperature: float = 0.9
    top_p: float = 0.92
    frequency_penalty: float = 0.4
    presence_penalty: float = 0.5
    max_tokens: int = 512
    answer_max_tokens: int = 200
    extra_body_thinking: str = "disabled"
    llm_request_timeout_seconds: int = 60
    llm_max_retries: int = 1

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
                if "extra_body" in item and not isinstance(item["extra_body"], dict):
                    raise SettingsError("LLM_PROFILES_JSON 的 extra_body 必须是对象")
        ids = [item["id"] for item in parsed]
        if len(set(ids)) != len(ids):
            raise SettingsError("LLM_PROFILES_JSON id 不可重复")
        if self.default_llm_profile not in ids:
            raise SettingsError(
                f"DEFAULT_LLM_PROFILE 必须在 LLM_PROFILES_JSON 中: {self.default_llm_profile}"
            )
        if self.llm_request_timeout_seconds <= 0:
            raise SettingsError("LLM_REQUEST_TIMEOUT_SECONDS 必须大于 0")
        if self.llm_max_retries < 0:
            raise SettingsError("LLM_MAX_RETRIES 不能为负")
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
                    extra_body=item.get("extra_body"),
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
