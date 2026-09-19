"""Enablement 串行链校验（dependency-graph 串行链的部署时 fail-fast）。

V2.0.0 ~ V2.6.0 段**已整体移除**：随 `vXX_` 开关体系删除，其 ON 路径已转常开，
无闸可校验（本文件只剩空实现，随收尾批次删除；调用点见 `app/main.py`）。

`action_outbox_enabled` 与 `foreground_gateway_enforced` 按裁决保留门控（已去版本前缀，见
flag-removal-audit.md 附录 E 与 F.10），它们不在任何依赖链上。
"""

from app.core.settings._shared import SettingsError


def enablement_violations(settings) -> list[str]:
    del settings
    return []


def validate_enablement_chain(settings) -> None:
    violations = enablement_violations(settings)
    if violations:
        raise SettingsError("V2 启用链配置错误：" + "；".join(violations))
