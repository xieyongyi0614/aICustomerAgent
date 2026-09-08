"""目标域设置（V6 Goal & Intention）：各 goal 类型完成/触发阈值。"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class GoalSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    goal_default_ttl_turns: int = 20
    goal_rest_complete_turns: int = 5
    goal_companion_complete_intensity: float = 0.4
    goal_repair_complete_tension: float = 0.3
    goal_repair_min_tension: float = 0.3
    goal_tease_familiarity: float = 0.4
    goal_tease_max_tension: float = 0.3
    goal_late_night_start: int = 23
    goal_late_night_end: int = 6
