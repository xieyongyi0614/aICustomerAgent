"""V2.6.0 Action Execution System 域设置（architecture.md Flag 表）。"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError

V26_MASTER_FLAG = "action_execution_enabled"
V26_SUB_FLAGS = (
    "action_abstraction_enabled",
    "action_scheduler_enabled",
    "action_multistep_enabled",
    "action_result_enabled",
    "action_feedback_enabled",
    "action_debug_enabled",
)
# 开了但当前版本无行为分支（对齐 v23 RESERVED 先例；启动告警非阻断）
RESERVED_V26_SUB_FLAGS = (
    "action_abstraction_enabled",
    "action_multistep_enabled",
)


class ActionExecutionSettings(BaseSettings):
    """6 个 `action_*` Flag（默认全 off，Flag off 时与 V2.5.0 逐字节一致）。"""

    model_config = DOMAIN_MODEL_CONFIG

    action_execution_enabled: bool = False
    action_abstraction_enabled: bool = False
    action_scheduler_enabled: bool = False
    action_multistep_enabled: bool = False
    action_result_enabled: bool = False
    action_feedback_enabled: bool = False

    action_schedule_default_priority: int = 100
    action_debug_enabled: bool = False

    @model_validator(mode="after")
    def validate_action_chain(self):
        master = self.action_execution_enabled
        for flag in V26_SUB_FLAGS:
            if getattr(self, flag) and not master:
                raise SettingsError(f"{flag} 要求 action_execution_enabled（V2.6.0 总闸先开）")
        if self.action_schedule_default_priority < 0:
            raise SettingsError("ACTION_SCHEDULE_DEFAULT_PRIORITY 不能为负")
        return self
