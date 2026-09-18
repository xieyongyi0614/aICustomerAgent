"""World Simulation 域设置（V2.3.0 WS-001）：世界模拟总闸与子闸及模拟参数。

总闸 + 子闸双开才生效；全部默认 off，关闭后行为与 V2.2.0 逐字节一致。

RESERVED 子闸：已定义并纳入总闸校验，但当前版本尚无行为分支，开启不生效。
上线前若运维误开会产生"看着开了但没变化"的困惑，故在启动时告警提示
（见 enablement.world_sim_reserved_flag_warnings）。
"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings

RESERVED_V23_SUB_FLAGS = ("habit_time_enabled",)
"""声明但未接线（WS-016 习惯时段延后交付）：开启不会产生行为变化。

`scene_expansion_enabled` 原列于此，实际已接线——`world_engine.py` 的
`movement.apply` 分支与 `services/tool/world_context.py` 的场景画像投影均读取它，
与 RESERVED 的「开启不产生行为变化」语义不符，故移出。
"""


class WorldSimulationSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    world_simulation_enabled: bool = False
    time_advance_enabled: bool = False
    daily_life_enabled: bool = False
    event_detection_enabled: bool = False
    scene_expansion_enabled: bool = False
    """已接线：gates 移动落点走 `movement.apply` 与场景画像投影（WS-016 部分交付）。"""
    habit_time_enabled: bool = False
    """RESERVED：习惯时段信号尚未实现（WS-016）。"""
    world_llm_assist_enabled: bool = False
    debug_tick_enabled: bool = False

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
