"""V2.6.0 Action Execution System 域设置。

`action_*` 五个 Flag 已随 `vXX_` 开关体系删除（执行层转常开）；仅存的调参项
`action_schedule_default_priority` 保留参数自校验（`validate_plan_config` 同款）。
"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


class ActionExecutionSettings(BaseSettings):
    """`action_schedule_default_priority` 调参项（Flag 已删，无门控语义）。"""

    model_config = DOMAIN_MODEL_CONFIG

    action_schedule_default_priority: int = 100

    @model_validator(mode="after")
    def validate_plan_config(self):
        if self.action_schedule_default_priority < 0:
            raise SettingsError("ACTION_SCHEDULE_DEFAULT_PRIORITY 不能为负")
        return self
