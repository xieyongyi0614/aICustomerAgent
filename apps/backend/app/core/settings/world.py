"""世界状态域设置（V8 World State）：时间模式、上下文、事件保留与快照。"""

import json

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class WorldSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    world_enabled: bool = True
    world_time_mode: str = "real_sync"
    world_sim_rate: float = 1.0
    world_context_char_budget: int = 600
    world_nearby_objects_limit: int = 3
    world_salient_events_limit: int = 3
    world_household_autoseed_enabled: bool = True
    world_interpreter_enabled: bool = True
    world_llm_assist_enabled: bool = False
    world_llm_assist_sample_rate: float = 0.2
    character_action_sync_enabled: bool = False
    character_action_sync_context_lines: int = 3
    inventory_grounding_enabled: bool = True
    inventory_grounding_mode: str = "rewrite"
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
    def validate_world_config(self):
        if self.world_time_mode not in ("real_sync", "simulated", "story"):
            raise SettingsError("WORLD_TIME_MODE 必须是 real_sync/simulated/story")
        if self.world_sim_rate <= 0:
            raise SettingsError("WORLD_SIM_RATE 必须大于 0")
        if self.inventory_grounding_mode not in ("off", "rewrite", "annotate"):
            raise SettingsError("INVENTORY_GROUNDING_MODE 必须是 off/rewrite/annotate")
        try:
            importance = json.loads(self.world_memory_importance_json)
        except json.JSONDecodeError as exc:
            raise SettingsError(f"WORLD_MEMORY_IMPORTANCE_JSON 解析失败: {exc}") from exc
        if not isinstance(importance, dict):
            raise SettingsError("WORLD_MEMORY_IMPORTANCE_JSON 必须是对象")
        return self

    def world_memory_importance(self) -> dict:
        return json.loads(self.world_memory_importance_json)
