"""Enablement 串行链校验（dependency-graph 串行链的部署时 fail-fast）。

V2.0.0 段**已整体移除**：`v2_autonomy_advanced_enabled` / `action_outbox_enabled` /
`v2_life_loop_enabled` 三个字段随 `vXX_` 开关体系删除，其 ON 路径已转常开。

V2.5.0 段（PLAN-002，architecture.md §7.10）：

| # | 链 |
|---|---|
| ① | 任一 plan_* 子闸开启 ⇒ `planning_enabled` |
| ② | `plan_execution_enabled` ⇒ `plan_scheduler_enabled` AND `action_enabled` |
| ③ | `plan_step_binding_enabled` ⇒ `planning_enabled`（①已覆盖）AND `tool_system_enabled` |
| ④ | `plan_tool_required` ⇒ `plan_step_binding_enabled` AND `tool_system_enabled` |
| ⑤ | `plan_reflection_enabled` ⇒ `planning_enabled`（①已覆盖） |
| ⑥ | `plan_memory_enabled` ⇒ `planning_enabled`（①已覆盖） |
| ⑦ | `plan_autonomy_enabled` ⇒ `planning_enabled`（①已覆盖）AND `agent_runtime_enabled` |

原 architecture §7.10 八条中的跨版本依赖（⇒ `v2_autonomy_advanced_enabled` +
`v2_life_loop_enabled`，以及 `v2_reflection_enabled` / `v2_memory_enabled`）随 V2.0.0 段
字段删除而消失；剩余七条中①为通用条目，②~⑦为跨版本依赖条目。

两处判定口径（均为「让默认配置自洽」的必要裁决）：

1. `plan_tool_required` **不进①的子闸循环**：它默认为 on，若按其字面量参与①，默认
   配置会立刻自我否决（总闸 off 而子闸 on）。它的语义是「计划编排启用后强制要求工具面」
   的策略修饰位，故以**有效闸值**参与判定：`planning_enabled AND
   plan_tool_required`，④随之只在总闸开启时生效。
2. ②~⑦的跨版本条目同用有效闸值判定：总闸 off 时计划编排层整体不参与，任何子闸要么已被
   ①拦下，要么本就是 off，跨版本依赖无判定意义。

②~⑦以 `V25_DEPENDENCIES` 数据表承载（源闸 → 依赖闸 → 中文理由），与 v23 段的子闸表、
v24 段的子闸表同款；①为 `V25_SUB_FLAGS` 上的子闸循环。

仅在启动边界调用（main.lifespan / 运维脚本），不做为模型级校验，
以保留子域隔离单测使用部分 Flag 组合的自由度。
"""

import logging

from app.core.settings._shared import SettingsError

_logger = logging.getLogger(__name__)

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
        "plan_step_binding_enabled",
        "tool_system_enabled",
        "（tool_id 指向 V2.4.0 工具定义）",
    ),
    (
        V25_TOOL_REQUIRED_FLAG,
        "plan_step_binding_enabled",
        "（要求工具面可用时步骤必须绑定工具；无面规划请关掉本开关）",
    ),
    (
        V25_TOOL_REQUIRED_FLAG,
        "tool_system_enabled",
        "（可用工具面来自 V2.4.0 工具系统）",
    ),
    (
        "plan_autonomy_enabled",
        "agent_runtime_enabled",
        "（plan_facts 经统一 Run 模型进自治决策）",
    ),
)


def enablement_violations(settings) -> list[str]:
    violations: list[str] = []
    if settings.unified_run_enabled and not settings.agent_runtime_enabled:
        violations.append(
            "unified_run_enabled 要求 agent_runtime_enabled"
            "（前台收编依赖统一 Run 模型）"
        )
    if (
        settings.personality_evolution_enabled
        and not settings.agent_runtime_enabled
    ):
        violations.append(
            "personality_evolution_enabled 要求 agent_runtime_enabled"
        )
    if settings.agent_metrics_enabled and not settings.agent_runtime_enabled:
        violations.append(
            "agent_metrics_enabled 要求 agent_runtime_enabled"
        )
    if (
        settings.personality_evolution_enabled
        and not settings.agent_metrics_enabled
    ):
        violations.append(
            "personality_evolution_enabled 要求 agent_metrics_enabled"
            "（反馈通道先于它反馈的对象上线）"
        )
    if settings.goal_stack_enabled and not settings.agent_runtime_enabled:
        violations.append(
            "goal_stack_enabled 要求 agent_runtime_enabled"
            "（Goal Stack 依赖 Run 阶段插槽）"
        )
    for sub_flag in (
        "emotion_transition_enabled",
        "relationship_addressing_enabled",
        "habit_runtime_enabled",
        "style_contract_enabled",
    ):
        if getattr(settings, sub_flag, False) and not settings.experience_enabled:
            violations.append(
                f"{sub_flag} 要求 experience_enabled（V2.2.0 总闸先开）"
            )
    v23_sub_flags = (
        "time_advance_enabled",
        "daily_life_enabled",
        "event_detection_enabled",
        "scene_expansion_enabled",
        "world_llm_assist_enabled",
        "debug_tick_enabled",
    )
    v23_master = getattr(settings, "world_simulation_enabled", False)
    v23_flags = {flag: getattr(settings, flag, False) for flag in v23_sub_flags}
    for sub_flag, enabled in v23_flags.items():
        if enabled and not v23_master:
            violations.append(
                f"{sub_flag} 要求 world_simulation_enabled（V2.3.0 总闸先开）"
            )
    if v23_flags["daily_life_enabled"] and not v23_flags[
        "time_advance_enabled"
    ]:
        violations.append(
            "daily_life_enabled 要求 time_advance_enabled"
            "（日程依赖日循环标记）"
        )
    if v23_flags["world_llm_assist_enabled"] and not v23_flags[
        "event_detection_enabled"
    ]:
        violations.append(
            "world_llm_assist_enabled 要求 event_detection_enabled"
            "（辅助服务于处境检出）"
        )
    v24_sub_flags = (
        "tool_permission_enabled",
        "tool_schema_validation_enabled",
        "tool_observation_enabled",
        "tool_surface_enabled",
        "tool_memory_enabled",
        "tool_reflection_enabled",
        "tool_channel_enabled",
        "tool_external_api_enabled",
        "tool_user_defined_enabled",
    )
    v24_master = getattr(settings, "tool_system_enabled", False)
    v24_flags = {flag: getattr(settings, flag, False) for flag in v24_sub_flags}
    for sub_flag, enabled in v24_flags.items():
        if enabled and not v24_master:
            violations.append(
                f"{sub_flag} 要求 tool_system_enabled（V2.4.0 总闸先开）"
            )
    if v24_flags["tool_channel_enabled"] and not getattr(
        settings, "feishu_enabled", False
    ):
        violations.append(
            "tool_channel_enabled 要求 feishu_enabled"
            "（channel.* 工具包装依赖飞书通道）"
        )
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


def tool_permission_sub_layer_warnings(settings) -> list[str]:
    """权限子闸未开启时的提示（非阻断）：总闸 on 而权限子闸 off。

    该组合不是"权限段不参与"（那是总闸 off 的语义），而是"特权工具默认拒绝"：
    免授权档（safe / normal）照常放行，sensitive / dangerous / `user.*` / `ext.api.*`
    因无可读授权存储而一律 `deny(permission_layer_disabled)`。做成 warning 而非
    violations，是为了保留子域单测使用"仅总闸"组合的自由度。
    """
    warnings: list[str] = []
    if not getattr(settings, "tool_system_enabled", False):
        return warnings
    if getattr(settings, "tool_permission_enabled", False):
        return warnings
    warnings.append(
        "tool_permission_enabled 未开启：sensitive / dangerous / user.* / ext.api.* "
        "工具将默认拒绝（fail-closed），仅 safe / normal 免授权档可执行"
    )
    return warnings


def validate_enablement_chain(settings) -> None:
    violations = enablement_violations(settings)
    if violations:
        raise SettingsError("V2 启用链配置错误：" + "；".join(violations))
    for message in tool_permission_sub_layer_warnings(settings):
        _logger.warning("V2.4.0 开关提示：%s", message)