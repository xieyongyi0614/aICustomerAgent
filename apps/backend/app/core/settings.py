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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_profiles_json: str = ""
    default_llm_profile: str = "longcat"
    temperature: float = 0.9
    top_p: float = 0.92
    frequency_penalty: float = 0.4
    presence_penalty: float = 0.5
    max_tokens: int = 512
    answer_max_tokens: int = 200
    extra_body_thinking: str = "disabled"

    database_url: str = "postgresql+psycopg://asuna:asuna@localhost:5432/asuna"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True

    summary_threshold: int = 40
    router_confidence_threshold: float = 0.5
    scene_intent_threshold: float = 0.5
    memory_importance_threshold: float = 0.6
    memory_top_k: int = 5
    memory_max_candidates: int = 3
    memory_conflict_threshold: float = 0.6
    memory_min_confidence: float = 0.6
    memory_min_score: float = 0.15
    memory_reclaim_interval_seconds: int = 3600

    emotion_max_turn_delta: float = 0.4
    emotion_strong_threshold: float = 0.6
    emotion_switch_min_confidence: float = 0.8
    emotion_inertia: float = 0.2
    emotion_decay_strong: float = 0.20
    emotion_decay_mild: float = 0.10
    emotion_decay_floor: float = 0.15
    emotion_rest_intensity: float = 0.3
    emotion_strong_boundary: float = 0.5

    rel_max_event_delta: float = 0.17
    rel_max_turn_delta: float = 0.15
    rel_max_day_delta: float = 0.30
    rel_tension_freeze: float = 0.5
    rel_replay_discount: float = 0.5
    rel_replay_min_idle_hours: float = 24.0
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
    log_content_preview_chars: int = 0

    default_user: str = "default-user"
    memory_recent_context_messages: int = 4
    memory_weight_lexical: float = 0.45
    memory_weight_importance: float = 0.25
    memory_weight_recency: float = 0.20
    memory_weight_type_affinity: float = 0.10
    memory_recency_half_life_days: float = 30.0
    memory_context_char_budget: int = 400
    memory_candidate_pool_limit: int = 200
    memory_reclaim_batch_limit: int = 500
    context_total_char_budget: int = 12000
    state_history_limit: int = 20
    scene_pending_max_turns: int = 5

    goal_default_ttl_turns: int = 20
    goal_rest_complete_turns: int = 5
    goal_companion_complete_intensity: float = 0.4
    goal_repair_complete_tension: float = 0.3
    goal_repair_min_tension: float = 0.3
    goal_tease_familiarity: float = 0.4
    goal_tease_max_tension: float = 0.3
    goal_late_night_start: int = 23
    goal_late_night_end: int = 6

    mode_switch_min_confidence: float = 0.7
    mode_switch_min_turns: int = 2
    mode_idle_reset_seconds: int = 7200
    habit_extra_json: str = "[]"

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

    evaluation_enabled: bool = True
    evaluation_persona_enabled: bool = True
    evaluation_emotion_enabled: bool = True
    evaluation_memory_enabled: bool = True
    evaluation_behavior_enabled: bool = True
    evaluation_autonomy_enabled: bool = True
    evaluation_llm_judge_enabled: bool = True
    evaluation_llm_judge_sample_rate: float = 1.0
    evaluation_judge_profile: str = ""
    evaluation_penalty_critical: float = 0.4
    evaluation_penalty_warning: float = 0.2
    evaluation_penalty_info: float = 0.05
    evaluation_fail_score: float = 0.6
    evaluation_warn_score: float = 0.85
    evaluation_overall_weights_json: str = (
        '{"turn": {"persona": 0.35, "emotion": 0.20, "memory": 0.20, "behavior": 0.25},'
        ' "proactive_action": {"autonomy": 0.60, "persona": 0.40}}'
    )
    evaluation_behavior_monotony_window: int = 5
    evaluation_behavior_monotony_threshold: int = 3
    evaluation_memory_missed_min_importance: float = 0.7
    evaluation_memory_missed_min_overlap: float = 0.3
    evaluation_proactive_reply_window_hours: int = 24
    evaluation_retention_days: int = 30
    evaluation_max_digest_chars: int = 2000

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
        return self

    @model_validator(mode="after")
    def validate_autonomy_quiet_hours(self):
        import re as _re

        pattern = _re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
        for name in ("autonomy_quiet_hours_start", "autonomy_quiet_hours_end"):
            value = getattr(self, name)
            if not pattern.match(value):
                raise SettingsError(f"{name} 必须是 HH:MM 格式: {value}")
        return self

    @model_validator(mode="after")
    def validate_evaluation_config(self):
        if not 0.0 <= self.evaluation_llm_judge_sample_rate <= 1.0:
            raise SettingsError("EVALUATION_LLM_JUDGE_SAMPLE_RATE 必须在 [0, 1]")
        try:
            weights = json.loads(self.evaluation_overall_weights_json)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"EVALUATION_OVERALL_WEIGHTS_JSON 解析失败: {exc}") from exc
        for subject in ("turn", "proactive_action"):
            table = weights.get(subject)
            if not isinstance(table, dict) or not table:
                raise SettingsError(f"EVALUATION_OVERALL_WEIGHTS_JSON 缺少主体权重表: {subject}")
            for dimension, weight in table.items():
                if not isinstance(weight, (int, float)) or weight < 0:
                    raise SettingsError(
                        f"EVALUATION_OVERALL_WEIGHTS_JSON {subject}.{dimension} 权重非法"
                    )
            total = sum(float(w) for w in table.values())
            if abs(total - 1.0) > 0.01:
                raise SettingsError(f"EVALUATION_OVERALL_WEIGHTS_JSON {subject} 权重之和应为 1.0")
        return self

    def evaluation_overall_weights(self, subject: str) -> dict:
        weights = json.loads(self.evaluation_overall_weights_json)
        return weights.get(subject, {})

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
