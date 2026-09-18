"""V2.5.0 Planning System 域设置（PLAN-002 / architecture.md §7.10）：计划编排总闸、12 个子闸与 14 个参数。

总闸 off 时零行为：`goal_planning` 走原路径、`goal_observation` 三事实源不变、
`goal_execution` 直构 `ActionIntent`、prompt 与 V2.4.0 逐字节一致。

`plan_tool_required` 是唯一默认为 on 的项：它不是「激活计划编排」的子闸，而是
「一旦启用计划编排，就强制要求工具面可用」的策略修饰位（off 时允许无面规划、退化为
V2.4.0 行为）。因此串行链校验把它按**总闸为前提**判定，否则默认配置会自我否决。
"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class PlanSettings(BaseSettings):
    """13 个 `plan_*` Flag + 14 个参数（默认值即 architecture.md §7.10 两张表）。"""

    model_config = DOMAIN_MODEL_CONFIG

    planning_enabled: bool = False
    plan_context_enabled: bool = False
    plan_step_binding_enabled: bool = False
    plan_scheduler_enabled: bool = False
    plan_execution_enabled: bool = False
    plan_observation_enabled: bool = False
    plan_revision_enabled: bool = False
    plan_memory_enabled: bool = False
    plan_reflection_enabled: bool = False
    plan_world_feedback_enabled: bool = False
    plan_autonomy_enabled: bool = False
    plan_tool_required: bool = True
    plan_debug_enabled: bool = False

    plan_max_steps: int = 5
    plan_max_depth: int = 2
    plan_step_max_attempts: int = 2
    plan_revision_budget: int = 3
    plan_ttl_hours: int = 168
    plan_step_cooldown_minutes: int = 30
    plan_observation_window_minutes: int = 120
    plan_context_memory_limit: int = 5
    plan_context_insight_limit: int = 5
    plan_llm_profile: str = ""
    plan_replan_min_confidence: float = 0.7
    plan_reflection_min_samples: int = 3
    plan_memory_importance_floor: float = 0.6
    plan_context_digest_enabled: bool = True

    @model_validator(mode="after")
    def validate_plan_config(self):
        """参数自校验（Task Detail §6.4 表）：违规即启动 fail-fast，理由中文可读。"""

        if self.plan_max_steps < 1:
            raise SettingsError("PLAN_MAX_STEPS 必须至少为 1")
        if self.plan_max_depth < 1:
            raise SettingsError("PLAN_MAX_DEPTH 必须至少为 1")
        if self.plan_step_max_attempts < 1:
            raise SettingsError("PLAN_STEP_MAX_ATTEMPTS 必须至少为 1")
        if self.plan_revision_budget < 0:
            raise SettingsError("PLAN_REVISION_BUDGET 不能为负（0 = 不许修订）")
        if self.plan_ttl_hours < 1:
            raise SettingsError("PLAN_TTL_HOURS 必须至少为 1")
        if self.plan_step_cooldown_minutes < 0:
            raise SettingsError("PLAN_STEP_COOLDOWN_MINUTES 不能为负")
        if self.plan_observation_window_minutes < 1:
            raise SettingsError("PLAN_OBSERVATION_WINDOW_MINUTES 必须至少为 1")
        if self.plan_context_memory_limit < 0:
            raise SettingsError("PLAN_CONTEXT_MEMORY_LIMIT 不能为负")
        if self.plan_context_insight_limit < 0:
            raise SettingsError("PLAN_CONTEXT_INSIGHT_LIMIT 不能为负")
        if not 0.0 <= self.plan_replan_min_confidence <= 1.0:
            raise SettingsError("PLAN_REPLAN_MIN_CONFIDENCE 必须落在 [0.0, 1.0]")
        if self.plan_reflection_min_samples < 1:
            raise SettingsError("PLAN_REFLECTION_MIN_SAMPLES 必须至少为 1")
        if not 0.0 <= self.plan_memory_importance_floor <= 1.0:
            raise SettingsError("PLAN_MEMORY_IMPORTANCE_FLOOR 必须落在 [0.0, 1.0]")
        return self
