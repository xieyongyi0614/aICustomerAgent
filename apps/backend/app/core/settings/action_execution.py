"""V2.6.0 Action Execution System 域设置（architecture.md Flag 表）。"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class ActionExecutionSettings(BaseSettings):
    """6 个 `v26_*` Flag（默认全 off，Flag off 时与 V2.5.0 逐字节一致）。"""

    model_config = DOMAIN_MODEL_CONFIG

    v26_action_execution_enabled: bool = False
    v26_action_abstraction_enabled: bool = False
    v26_action_scheduler_enabled: bool = False
    v26_action_multistep_enabled: bool = False
    v26_action_result_enabled: bool = False
    v26_action_feedback_enabled: bool = False

    v26_action_schedule_default_priority: int = 100
    v26_action_debug_enabled: bool = False

    @model_validator(mode="after")
    def validate_v26_chain(self):
        master = self.v26_action_execution_enabled
        for flag in (
            "v26_action_abstraction_enabled",
            "v26_action_scheduler_enabled",
            "v26_action_multistep_enabled",
            "v26_action_result_enabled",
            "v26_action_feedback_enabled",
            "v26_action_debug_enabled",
        ):
            if getattr(self, flag) and not master:
                raise SettingsError(f"{flag} 要求 v26_action_execution_enabled（V2.6.0 总闸先开）")
        if self.v26_action_schedule_default_priority < 0:
            raise SettingsError("V26_ACTION_SCHEDULE_DEFAULT_PRIORITY 不能为负")
        return self
