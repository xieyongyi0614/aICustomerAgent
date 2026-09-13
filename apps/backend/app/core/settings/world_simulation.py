"""World Simulation 域设置（V2.3.0 WS-001）：世界模拟总闸与子闸及模拟参数。

总闸 + 子闸双开才生效；全部默认 off，关闭后行为与 V2.2.0 逐字节一致。
"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class WorldSimulationSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    v23_world_simulation_enabled: bool = False
    v23_time_advance_enabled: bool = False
    v23_daily_life_enabled: bool = False
    v23_event_detection_enabled: bool = False
    v23_scene_expansion_enabled: bool = False
    v23_habit_time_enabled: bool = False
    v23_world_llm_assist_enabled: bool = False
    v23_debug_tick_enabled: bool = False

    world_sim_interval_seconds: int = 60
    sim_advance_max_minutes: int = 120
    world_event_tick_cap: int = 8
    catch_up_max_days: int = 7
    world_brief_char_budget: int = 400
    world_context_char_budget_v23: int = 1000
    daily_plan_retention_days: int = 30
    user_situation_valid_hours: int = 48
    v23_part_boundaries_json: str = (
        '{"morning":360,"noon":690,"afternoon":840,"evening":1080,"night":1320}'
    )
    v23_llm_assist_sample_rate: float = 0.2
    v23_event_escalation_types: str = (
        "user_condition,weather_change,calendar_event,goal_completed"
    )
    v23_interest_confidence_threshold: float = 0.7
