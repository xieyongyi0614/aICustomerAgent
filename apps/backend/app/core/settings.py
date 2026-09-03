from functools import lru_cache

import json

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.action import ACTION_TYPES


class SettingsError(Exception):
    pass


_OBSERVABILITY_PROMPT_MODES = ("disabled", "sampled", "always")

STAGE_KEYS = ("stranger", "friend", "close_friend", "partner")


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
    rel_evolution_enabled: bool = True
    rel_repetition_decay: float = 0.7
    rel_trust_negative_amp: float = 1.5
    rel_comfort_drift: float = 0.05
    rel_comfort_baseline_json: str = (
        '{"stranger": 0.45, "friend": 0.60, "close_friend": 0.70, "partner": 0.80}'
    )
    rel_milestone_delta_cap: float = 0.10
    rel_signal_llm_enabled: bool = False
    rel_signal_evidence_window: int = 20
    rel_milestone_enabled: bool = True
    rel_conflict_enabled: bool = True
    rel_conflict_cold_hours: float = 12.0
    rel_conflict_max_cold_days: float = 7.0
    rel_conflict_recover_positive: int = 2
    rel_neglect_days_json: str = '{"stranger": 7, "friend": 5, "close_friend": 3, "partner": 2}'
    rel_tension_daily_decay: float = 0.02
    rel_autonomy_trust_floor: float = 0.45
    rel_snapshot_keep: int = 20
    action_enabled: bool = False
    action_detector_enabled: bool = True
    action_llm_assist_enabled: bool = False
    action_llm_assist_sample_rate: float = 0.0
    action_plan_max_steps: int = 1
    action_plan_expires_minutes: int = 5
    action_plan_expiry_hours: int = 24
    action_max_active_per_user: int = 5
    action_dedupe_window_hours: int = 24
    action_execution_timeout_seconds: int = 10
    action_retry_max_attempts: int = 2
    action_retry_backoff_seconds: int = 30
    action_maintenance_interval_seconds: int = 60
    action_context_char_budget: int = 400
    action_memory_policy_enabled: bool = True
    action_memory_policy_json: str = (
        '{"create_reminder": {"deposit": true, "memory_type": "important_event",'
        ' "importance": 0.7, "source": "user_derived"},'
        ' "cancel_reminder": {"deposit": true, "memory_type": "important_event",'
        ' "importance": 0.5, "source": "user_derived"},'
        ' "remember_fact": {"deposit": true, "memory_type": "user_fact",'
        ' "importance": 0.8, "source": "user_stated"},'
        ' "create_object": {"deposit": true, "memory_type": "user_preference",'
        ' "importance": 0.5, "source": "user_derived"}}'
    )
    action_relationship_enabled: bool = False
    action_record_retention_days: int = 180
    autonomy_action_enabled: bool = False
    autonomy_action_daily_limit: int = 1
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
        '{"turn": {"persona": 0.30, "emotion": 0.18, "memory": 0.18,'
        ' "behavior": 0.24, "action": 0.10},'
        ' "proactive_action": {"autonomy": 0.60, "persona": 0.40}}'
    )
    evaluation_behavior_monotony_window: int = 5
    evaluation_behavior_monotony_threshold: int = 3
    evaluation_expression_density_low: float = 0.01
    evaluation_expression_density_high: float = 0.10
    evaluation_memory_missed_min_importance: float = 0.7
    evaluation_memory_missed_min_overlap: float = 0.15
    evaluation_memory_support_min_overlap: float = 0.2
    evaluation_proactive_reply_window_hours: int = 24
    evaluation_retention_days: int = 30
    evaluation_world_consistency_enabled: bool = True
    evaluation_relationship_enabled: bool = True
    evaluation_action_enabled: bool = True
    evaluation_max_digest_chars: int = 2000

    observability_persist_enabled: bool = True
    observability_trace_sample_rate: float = 1.0
    observability_prompt_capture_mode: str = "sampled"
    observability_prompt_sample_rate: float = 0.2
    observability_prompt_max_chars: int = 20000
    observability_step_extra_max_chars: int = 2000
    observability_prompt_redact: bool = False
    observability_llm_cost_json: str = "{}"
    observability_trace_retention_days: int = 7
    observability_prompt_retention_days: int = 3
    observability_decision_retention_days: int = 14
    observability_llm_call_retention_days: int = 30
    observability_cleanup_interval_hours: int = 24

    world_enabled: bool = True
    world_time_mode: str = "real_sync"
    world_sim_rate: float = 1.0
    world_context_char_budget: int = 600
    world_nearby_objects_limit: int = 3
    world_salient_events_limit: int = 3
    world_interpreter_enabled: bool = True
    world_llm_assist_enabled: bool = False
    world_llm_assist_sample_rate: float = 0.2
    world_active_entities_limit: int = 200
    world_active_events_limit: int = 20
    world_event_grace_hours: float = 6.0
    world_memory_bridge_enabled: bool = True
    world_memory_importance_json: str = '{"normal": 0.6, "high": 0.8}'
    world_event_retention_days: int = 90
    world_snapshot_retention_days: int = 30
    world_snapshot_max_per_world: int = 20
    world_maintenance_interval_seconds: int = 60

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

    @model_validator(mode="after")
    def validate_observability_config(self):
        if not 0.0 <= self.observability_trace_sample_rate <= 1.0:
            raise SettingsError("OBSERVABILITY_TRACE_SAMPLE_RATE 必须在 [0, 1]")
        if self.observability_prompt_capture_mode not in _OBSERVABILITY_PROMPT_MODES:
            raise SettingsError(
                "OBSERVABILITY_PROMPT_CAPTURE_MODE 必须是 disabled/sampled/always"
            )
        if not 0.0 <= self.observability_prompt_sample_rate <= 1.0:
            raise SettingsError("OBSERVABILITY_PROMPT_SAMPLE_RATE 必须在 [0, 1]")
        try:
            cost_table = json.loads(self.observability_llm_cost_json)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"OBSERVABILITY_LLM_COST_JSON 解析失败: {exc}") from exc
        if not isinstance(cost_table, dict):
            raise SettingsError("OBSERVABILITY_LLM_COST_JSON 必须是对象")
        return self

    def observability_llm_cost_table(self) -> dict:
        return json.loads(self.observability_llm_cost_json)

    @model_validator(mode="after")
    def validate_action_config(self):
        if self.action_llm_assist_sample_rate < 0 or self.action_llm_assist_sample_rate > 1.0:
            raise SettingsError("ACTION_LLM_ASSIST_SAMPLE_RATE 必须在 [0, 1]")
        if self.action_plan_max_steps < 1:
            raise SettingsError("ACTION_PLAN_MAX_STEPS 必须至少为 1")
        if self.action_max_active_per_user < 1:
            raise SettingsError("ACTION_MAX_ACTIVE_PER_USER 必须至少为 1")
        if self.action_execution_timeout_seconds <= 0:
            raise SettingsError("ACTION_EXECUTION_TIMEOUT_SECONDS 必须大于 0")
        if self.action_retry_max_attempts < 1:
            raise SettingsError("ACTION_RETRY_MAX_ATTEMPTS 必须至少为 1")
        try:
            policy = json.loads(self.action_memory_policy_json)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"ACTION_MEMORY_POLICY_JSON 解析失败: {exc}") from exc
        if not isinstance(policy, dict):
            raise SettingsError("ACTION_MEMORY_POLICY_JSON 必须是对象")
        for action_type, row in policy.items():
            if action_type not in ACTION_TYPES:
                raise SettingsError(f"ACTION_MEMORY_POLICY_JSON 未知行动类型: {action_type}")
            if not isinstance(row, dict) or "deposit" not in row:
                raise SettingsError(f"ACTION_MEMORY_POLICY_JSON {action_type} 行非法")
            if row.get("deposit"):
                source = row.get("source")
                if source not in ("user_stated", "user_derived"):
                    raise SettingsError(
                        f"ACTION_MEMORY_POLICY_JSON {action_type} source 必须是 user_stated/user_derived"
                    )
        return self

    def action_memory_policy(self) -> dict:
        return json.loads(self.action_memory_policy_json)

    @model_validator(mode="after")
    def validate_world_config(self):
        if self.world_time_mode not in ("real_sync", "simulated", "story"):
            raise SettingsError("WORLD_TIME_MODE 必须是 real_sync/simulated/story")
        if self.world_sim_rate <= 0:
            raise SettingsError("WORLD_SIM_RATE 必须大于 0")
        try:
            importance = json.loads(self.world_memory_importance_json)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"WORLD_MEMORY_IMPORTANCE_JSON 解析失败: {exc}") from exc
        if not isinstance(importance, dict):
            raise SettingsError("WORLD_MEMORY_IMPORTANCE_JSON 必须是对象")
        return self

    def world_memory_importance(self) -> dict:
        return json.loads(self.world_memory_importance_json)

    @model_validator(mode="after")
    def validate_rel_config(self):
        for name in ("rel_comfort_baseline_json", "rel_neglect_days_json"):
            try:
                table = json.loads(getattr(self, name))
            except json.JSONDecodeError as exc:
                raise SettingsError(f"{name} 解析失败: {exc}") from exc
            if not isinstance(table, dict) or not table:
                raise SettingsError(f"{name} 必须是非空对象")
        for stage in STAGE_KEYS:
            baselines = json.loads(self.rel_comfort_baseline_json)
            if stage not in baselines:
                raise SettingsError(f"rel_comfort_baseline_json 缺少阶段: {stage}")
            thresholds = json.loads(self.rel_neglect_days_json)
            if stage not in thresholds:
                raise SettingsError(f"rel_neglect_days_json 缺少阶段: {stage}")
        return self

    def comfort_baselines(self) -> dict:
        return json.loads(self.rel_comfort_baseline_json)

    def neglect_thresholds(self) -> dict:
        return json.loads(self.rel_neglect_days_json)

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
