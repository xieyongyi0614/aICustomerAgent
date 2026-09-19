"""Enablement 串行链校验（dependency-graph 串行链的部署时 fail-fast）。

V2.0.0 / V2.1.0 / V2.2.0 / V2.3.0 / V2.4.0 / V2.5.0 段**已整体移除**：随 `vXX_` 开关体系
删除，其 ON 路径已转常开，无闸可校验。计划编排段（V2.5.0）连同 `planning_enabled` 总闸与
11 个子闸一并消失，`plan_step_binding_enabled` / `plan_tool_required` 对 `tool_system_enabled`
的跨域依赖、以及 `plan_tool_required ⇒ plan_step_binding_enabled` 的版本内依赖随之作废
（保留的两个策略位 `plan_tool_required` / `plan_context_digest_enabled` 不在任何依赖链上）。

`action_outbox_enabled` 与 `foreground_gateway_enforced` 按裁决保留门控（已去版本前缀，见
flag-removal-audit.md 附录 E 与 F.10），它们不在任何依赖链上。

V2.6.0 段（ACTION-001）：总闸 + 子闸，见下表。

| # | 链 |
|---|---|
| ① | `action_execution_enabled`（总闸）⇒ `action_enabled` |
| ② | 任一 action_* 子闸开启 ⇒ `action_execution_enabled` |

仅在启动边界调用（main.lifespan / 运维脚本），不做为模型级校验，
以保留子域隔离单测使用部分 Flag 组合的自由度。
"""

from app.core.settings._shared import SettingsError


def enablement_violations(settings) -> list[str]:
    violations: list[str] = []

    from app.core.settings.action_execution import V26_MASTER_FLAG, V26_SUB_FLAGS

    v26_master = getattr(settings, V26_MASTER_FLAG, False)
    if v26_master and not getattr(settings, "action_enabled", False):
        violations.append(
            "action_execution_enabled 要求 action_enabled"
            "（执行层依赖 V9 行动总闸）"
        )
    for sub_flag in V26_SUB_FLAGS:
        if getattr(settings, sub_flag, False) and not v26_master:
            violations.append(
                f"{sub_flag} 要求 {V26_MASTER_FLAG}（V2.6.0 总闸先开）"
            )
    return violations


def validate_enablement_chain(settings) -> None:
    violations = enablement_violations(settings)
    if violations:
        raise SettingsError("V2 启用链配置错误：" + "；".join(violations))
