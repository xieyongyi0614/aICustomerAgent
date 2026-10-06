"""V2.5.0 Planning System 域设置（PLAN-002 / architecture.md §7.10）：策略位与 14 个参数。

计划编排已随 `vXX_` 开关体系删除而**转正常开**：总闸 `planning_enabled` 与 11 个子闸
不复存在，原「总闸 off ⇒ 走 V2.4.0 原路径」的退化分支整体消失（`goal_planning` /
`goal_observation` / `goal_execution` 改为恒走计划编排路径）。

保留**策略位** `plan_tool_required`（默认 ON、已去版本前缀、零门控污染）：要求工具面可用时
步骤必须绑定工具，off 允许无面规划——它不是「激活计划编排」的开关，而是编排启用后的行为
修饰位。`plan_context_digest_enabled` 已按批次 2 固化常开并删字段（计划落库恒写
`context_digest`）。
"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class PlanSettings(BaseSettings):
    """1 个 `plan_*` 策略位 + 14 个参数（默认值即 architecture.md §7.10 两张表）。"""

    model_config = DOMAIN_MODEL_CONFIG

    plan_tool_required: bool = True

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
