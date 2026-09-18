"""行动域设置（V9 Action Engine）：检测/规划/执行/重试 + 记忆存入策略。"""

import json

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError
from app.models.action import ACTION_TYPES


class ActionSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    action_enabled: bool = False
    action_detector_enabled: bool = True
    # V2.6.1 裁决：多步未交付；保持 1（多步 Flag 从未接线，已随死开关删除）。
    action_plan_max_steps: int = 1
    action_plan_expires_minutes: int = 5
    action_plan_expiry_hours: int = 24
    action_max_active_per_user: int = 5
    action_dedupe_window_hours: int = 24
    action_execution_timeout_seconds: int = 10
    action_retry_max_attempts: int = 2
    action_retry_backoff_seconds: int = 30
    action_executing_timeout_minutes: int = 30
    action_maintenance_interval_seconds: int = 60
    chat_rate_limit_per_minute: int = 30
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

    @model_validator(mode="after")
    def validate_action_config(self):
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
