"""邮件通道域设置：SMTP 发件与验证码策略（邮箱验证码登录）。"""

from pydantic import model_validator

from app.core.settings._shared import (
    DOMAIN_MODEL_CONFIG,
    BaseSettings,
    SettingsError,
)

_POSITIVE_INT_FIELDS = (
    "email_code_ttl_seconds",
    "email_code_cooldown_seconds",
    "email_code_send_hourly_cap",
    "email_code_send_daily_cap",
    "email_code_max_attempts",
)


class EmailSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    email_provider: str = "smtp"
    email_smtp_host: str = ""
    email_smtp_port: int = 465
    email_smtp_ssl: bool = True
    email_smtp_user: str = ""
    email_smtp_password: str = ""
    email_from_address: str = ""
    email_from_name: str = "朝夕"
    email_code_ttl_seconds: int = 300
    email_code_cooldown_seconds: int = 60
    email_code_send_hourly_cap: int = 6
    email_code_send_daily_cap: int = 20
    email_code_max_attempts: int = 5

    @model_validator(mode="after")
    def validate_email_config(self):
        if self.email_provider != "smtp":
            raise SettingsError(f"不支持的 EMAIL_PROVIDER: {self.email_provider}")
        if self.email_smtp_port <= 0:
            raise SettingsError("EMAIL_SMTP_PORT 必须大于 0")
        for field_name in _POSITIVE_INT_FIELDS:
            if getattr(self, field_name) <= 0:
                raise SettingsError(f"{field_name.upper()} 必须大于 0")
        if self.email_smtp_host:
            missing = [
                env_name
                for env_name, value in (
                    ("EMAIL_SMTP_USER", self.email_smtp_user),
                    ("EMAIL_SMTP_PASSWORD", self.email_smtp_password),
                    ("EMAIL_FROM_ADDRESS", self.email_from_address),
                )
                if not value
            ]
            if missing:
                raise SettingsError(
                    f"配置了 EMAIL_SMTP_HOST 时缺少必需配置: {', '.join(missing)}"
                )
        return self

    def smtp_configured(self) -> bool:
        return bool(
            self.email_smtp_host and self.email_smtp_user and self.email_smtp_password
        )

    def from_header(self) -> str:
        address = self.email_from_address or self.email_smtp_user
        if not address:
            return ""
        if self.email_from_name:
            return f"{self.email_from_name} <{address}>"
        return address
