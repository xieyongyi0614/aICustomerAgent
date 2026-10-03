"""调试台面门禁设置（ADR-16 §7：/debug/*、/state、action、world 端点）。

`DEBUG_SURFACE_ENFORCED=true`（生产部署应显式设置）时调试台面统一 404 防探测；
默认 `false` 供开发与调试台使用。命名遵循冻结开关基线（PLA-018 AC6）：禁止新增
`*_enabled` 字段，策略位按领域语义命名（先例 `foreground_gateway_enforced`）。
"""

from app.core.settings._shared import DOMAIN_MODEL_CONFIG, BaseSettings


class DebugSettings(BaseSettings):
    model_config = DOMAIN_MODEL_CONFIG

    debug_surface_enforced: bool = False
