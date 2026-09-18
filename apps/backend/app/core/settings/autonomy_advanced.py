"""Autonomy Advanced 域设置（V2.0.0 AUT）：规划/子目标/补给/仲裁。"""

import json

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class AutonomyAdvancedSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    v2_autonomy_planning_llm_profile: str = ""
    v2_autonomy_planning_max_attempts: int = 3
    v2_autonomy_subgoal_max_count: int = 5
    v2_autonomy_subgoal_max_depth: int = 2
    v2_autonomy_supply_interval_minutes: int = 720
    v2_autonomy_supply_personal_min_weight: float = 0.3
    v2_autonomy_supply_relationship_min_strength: float = 0.6
    v2_autonomy_supply_world_min_salience: float = 0.85
    v2_autonomy_supply_templates_json: str = (
        '{"personal": "在用户在意的话题上更进一步",'
        ' "relationship": "让彼此的陪伴更近一步"}'
    )
    v2_autonomy_subgoal_failure_threshold: int = 3
    v2_autonomy_goal_max_active_hours: int = 168
    v2_autonomy_subgoal_execute_cooldown_minutes: int = 30
    v2_autonomy_observation_window_minutes: int = 120
    v2_autonomy_abandon_min_progress_days: int = 14
    v2_autonomy_arbitration_interval_minutes: int = 60
    v2_autonomy_priority_layer_weight_long: float = 1.0
