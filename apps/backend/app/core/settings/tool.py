"""V2.4.0 Tool System 域设置（TOOL-001）：工具系统总闸与九个子闸及治理参数。

总闸 + 子闸双开才生效；全部默认 off，关闭后行为与 V2.3.0 逐字节一致。
"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


def parse_csv_values(value: str) -> frozenset[str]:
    return frozenset(part for part in (item.strip() for item in value.split(",")) if part)


class ToolSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    tool_system_enabled: bool = False
    tool_permission_enabled: bool = False
    tool_schema_validation_enabled: bool = False
    tool_observation_enabled: bool = False
    tool_surface_enabled: bool = False
    tool_memory_enabled: bool = False
    tool_reflection_enabled: bool = False
    tool_channel_enabled: bool = False
    tool_external_api_enabled: bool = False
    tool_user_defined_enabled: bool = False

    tool_disabled_ids: str = ""
    tool_surface_max_tools: int = 12
    tool_breaker_threshold: int = 3
    tool_breaker_cooldown_seconds: int = 300
    tool_confirm_timeout_hours: int = 24
    tool_confirm_ttl_reuse: bool = True
    tool_audit_retention_days: int = 180
    tool_ext_manifest_path: str = ""
    tool_ext_allowed_hosts: str = ""

    @model_validator(mode="after")
    def validate_tool_config(self):
        if self.tool_surface_max_tools < 1:
            raise SettingsError("TOOL_SURFACE_MAX_TOOLS 必须至少为 1")
        if self.tool_breaker_threshold <= 0:
            raise SettingsError("TOOL_BREAKER_THRESHOLD 必须大于 0")
        if self.tool_breaker_cooldown_seconds <= 0:
            raise SettingsError("TOOL_BREAKER_COOLDOWN_SECONDS 必须大于 0")
        if self.tool_confirm_timeout_hours <= 0:
            raise SettingsError("TOOL_CONFIRM_TIMEOUT_HOURS 必须大于 0")
        if self.tool_audit_retention_days <= 0:
            raise SettingsError("TOOL_AUDIT_RETENTION_DAYS 必须大于 0")
        return self

    def disabled_tool_ids(self) -> frozenset[str]:
        return parse_csv_values(self.tool_disabled_ids)

    def allowed_ext_hosts(self) -> frozenset[str]:
        return parse_csv_values(self.tool_ext_allowed_hosts)
