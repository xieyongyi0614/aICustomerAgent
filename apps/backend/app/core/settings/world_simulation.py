"""World Simulation 域设置（V2.3.0 WS-001）：世界模拟调参。

开关已随 flag 体系删除固化常开；本模块仅保留模拟参数与预算旋钮。
"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class WorldSimulationSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    world_sim_interval_seconds: int = 60
    sim_advance_max_minutes: int = 120
    world_event_tick_cap: int = 8
    catch_up_max_days: int = 7
    world_brief_char_budget: int = 400
    world_context_char_budget_v23: int = 1000
    daily_plan_retention_days: int = 30
    user_situation_valid_hours: int = 48
    part_boundaries_json: str = (
        '{"morning":360,"noon":690,"afternoon":840,"evening":1080,"night":1320}'
    )
    world_llm_assist_sample_rate: float = 0.2
    world_event_escalation_types: str = (
        "user_condition,weather_change,calendar_event,goal_completed"
    )
    interest_confidence_threshold: float = 0.7
