"""关系域设置（V5）：数值动力学 + 安抚基线/忽视阈值 + 冲突。"""

import json

from pydantic import model_validator

from app.core.settings._shared import (
    DOMAIN_MODEL_CONFIG,
    STAGE_KEYS,
    BaseSettings,
    SettingsError,
)


class RelationshipSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

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
