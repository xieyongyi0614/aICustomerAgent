"""个人生活域设置：PLA-002 / PLA-003 / PLA-004 参数类字段落点。

仅允许参数类字段（阈值 / 取值 / 文案 / 周期），禁止 `*_enabled` 功能位。
"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class LifeSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG
