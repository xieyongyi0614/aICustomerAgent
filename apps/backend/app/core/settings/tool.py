"""V2.4.0 Tool System 域设置（TOOL-001）：治理参数。

原总闸 `tool_system_enabled` 与九个子闸（permission / schema_validation /
observation / surface / memory / reflection / channel / external_api /
user_defined）已随 V2.4.0 转正删除——工具系统无条件生效，不再有配置面。
`tool_confirm_ttl_reuse` 按裁决保留：它不是部署闸门，而是「批准是否跨轮复用」
的策略修饰位（默认 ON）。
"""

from pydantic import model_validator

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings, SettingsError


def parse_csv_values(value: str) -> frozenset[str]:
    return frozenset(part for part in (item.strip() for item in value.split(",")) if part)


class ToolSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

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
