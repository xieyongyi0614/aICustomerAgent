"""观测域设置（V7.8 Observability）：采样、脱敏、成本表、保留期。"""

import json

from pydantic import model_validator

from app.core.settings._shared import (
    DOMAIN_MODEL_CONFIG,
    _OBSERVABILITY_PROMPT_MODES,
    BaseSettings,
    SettingsError,
)


class ObservabilitySettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

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
