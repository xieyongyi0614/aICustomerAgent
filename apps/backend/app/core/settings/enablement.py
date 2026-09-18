"""Enablement 串行链校验（dependency-graph 串行链的部署时 fail-fast）。

V2.0.0 / V2.1.0 / V2.2.0 / V2.3.0 段**已整体移除**：随 `vXX_` 开关体系删除，
其 ON 路径已转常开，无闸可校验。V2.4.0 段（TOOL-001）同批移除——工具系统总闸与
九个子闸已随该版本转正删除，`tool_system_enabled` 不再是链上节点，
`plan_step_binding_enabled` / `plan_tool_required` 对它的两条跨域依赖随之消失。
`action_outbox_enabled` 与 `foreground_gateway_enforced` 按裁决保留门控（已去版本
前缀，见 flag-removal-audit.md 附录 E 与 F.10），它们不在任何依赖链上。

V2.5.0 段（PLAN-002，architecture.md §7.10）：

| # | 链 |
|---|---|
| ① | 任一 plan_* 子闸开启 ⇒ `planning_enabled` |
| ② | `plan_execution_enabled` ⇒ `plan_scheduler_enabled` AND `action_enabled` |
| ③ | `plan_step_binding_enabled` ⇒ `planning_enabled`（①已覆盖） |
| ④ | `plan_tool_required` ⇒ `plan_step_binding_enabled` |
| ⑤ | `plan_reflection_enabled` ⇒ `planning_enabled`（①已覆盖） |
| ⑥ | `plan_memory_enabled` ⇒ `planning_enabled`（①已覆盖） |

原 architecture §7.10 八条中的跨版本依赖——⇒ V2.0.0 的自治/生命循环/反思/记忆四闸、
⇒ V2.1.0 统一 Run 模型（`plan_autonomy_enabled` 那条）、⇒ V2.4.0 工具系统的两条
——随对应字段删除而消失；剩余条目中①为通用条目，②为跨域依赖条目。

两处判定口径（均为「让默认配置自洽」的必要裁决）：

1. `plan_tool_required` **不进①的子闸循环**：它默认为 on，若按其字面量参与①，默认
   配置会立刻自我否决（总闸 off 而子闸 on）。它的语义是「计划编排启用后强制要求工具面」
   的策略修饰位，故以**有效闸值**参与判定：`planning_enabled AND
   plan_tool_required`，④随之只在总闸开启时生效。
2. ②的跨域条目同用有效闸值判定：总闸 off 时计划编排层整体不参与，任何子闸要么已被
   ①拦下，要么本就是 off，跨域依赖无判定意义。

②以 `V25_DEPENDENCIES` 数据表承载（源闸 → 依赖闸 → 中文理由）；
①④分别由 `V25_SUB_FLAGS` 上的子闸循环与依赖表承载。

仅在启动边界调用（main.lifespan / 运维脚本），不做为模型级校验，
以保留子域隔离单测使用部分 Flag 组合的自由度。
"""

from app.core.settings._shared import SettingsError

V25_MASTER_FLAG = "planning_enabled"
V25_TOOL_REQUIRED_FLAG = "plan_tool_required"

V25_SUB_FLAGS: tuple[str, ...] = (
    "plan_context_enabled",
    "plan_step_binding_enabled",
    "plan_scheduler_enabled",
    "plan_execution_enabled",
    "plan_observation_enabled",
    "plan_revision_enabled",
    "plan_memory_enabled",
    "plan_reflection_enabled",
    "plan_world_feedback_enabled",
    "plan_autonomy_enabled",
    "plan_debug_enabled",
)

V25_GATE_FLAGS: tuple[str, ...] = (
    V25_MASTER_FLAG,
    V25_TOOL_REQUIRED_FLAG,
    *V25_SUB_FLAGS,
)

V25_DEPENDENCIES: tuple[tuple[str, str, str], ...] = (
    ("plan_execution_enabled", "plan_scheduler_enabled", "（先开调度子闸）"),
    ("plan_execution_enabled", "action_enabled", "（步骤执行经 V9 行动引擎）"),
    (
        V25_TOOL_REQUIRED_FLAG,
        "plan_step_binding_enabled",
        "（要求工具面可用时步骤必须绑定工具；无面规划请关掉本开关）",
    ),
)


def enablement_violations(settings) -> list[str]:
    violations: list[str] = []
    v25_gates = {flag: getattr(settings, flag, False) for flag in V25_GATE_FLAGS}
    v25_effective_gates = {
        **v25_gates,
        V25_TOOL_REQUIRED_FLAG: v25_gates[V25_MASTER_FLAG]
        and v25_gates[V25_TOOL_REQUIRED_FLAG],
    }
    for sub_flag in V25_SUB_FLAGS:
        if v25_gates[sub_flag] and not v25_gates[V25_MASTER_FLAG]:
            violations.append(
                f"{sub_flag} 要求 {V25_MASTER_FLAG}（V2.5.0 总闸先开）"
            )
    for required_flag, dependency, reason in V25_DEPENDENCIES:
        if v25_effective_gates[required_flag] and not getattr(
            settings, dependency, False
        ):
            violations.append(f"{required_flag} 要求 {dependency}{reason}")

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