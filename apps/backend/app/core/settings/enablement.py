"""V2.0.0 Enablement 串行链校验（dependency-graph 串行链的部署时 fail-fast）。

规则（docs/version/v2.0.0/architecture/dependency-graph.md §1 + phase-6 附录）：
- v2_autonomy_advanced_enabled 依赖 v2_life_loop_enabled 且 action_enabled（Sub-Goal
  执行经 outbox + Life Loop 消费 + V9 行动总闸）。
- v2_action_outbox_enabled 依赖 v2_life_loop_enabled（无消费器的 outbox 会死信堆积）。

仅在启动边界调用（main.lifespan / 运维脚本），不做为模型级校验，
以保留子域隔离单测使用部分 Flag 组合的自由度。
"""

import logging

from app.core.settings._shared import SettingsError

_logger = logging.getLogger(__name__)


def enablement_violations(settings) -> list[str]:
    violations: list[str] = []
    if settings.v2_autonomy_advanced_enabled:
        if not settings.v2_life_loop_enabled:
            violations.append(
                "v2_autonomy_advanced_enabled 要求 v2_life_loop_enabled"
                "（Sub-Goal 执行依赖 Life Loop 消费 outbox）"
            )
        if not settings.action_enabled:
            violations.append(
                "v2_autonomy_advanced_enabled 要求 action_enabled"
                "（Sub-Goal 执行依赖 V9 行动总闸）"
            )
    if settings.v2_action_outbox_enabled and not settings.v2_life_loop_enabled:
        violations.append(
            "v2_action_outbox_enabled 要求 v2_life_loop_enabled"
            "（无消费器的 outbox 将死信堆积）"
        )
    if settings.v21_unified_run_enabled and not settings.v21_agent_runtime_enabled:
        violations.append(
            "v21_unified_run_enabled 要求 v21_agent_runtime_enabled"
            "（前台收编依赖统一 Run 模型）"
        )
    if (
        settings.v21_personality_evolution_enabled
        and not settings.v21_agent_runtime_enabled
    ):
        violations.append(
            "v21_personality_evolution_enabled 要求 v21_agent_runtime_enabled"
        )
    if settings.v21_agent_metrics_enabled and not settings.v21_agent_runtime_enabled:
        violations.append(
            "v21_agent_metrics_enabled 要求 v21_agent_runtime_enabled"
        )
    if (
        settings.v21_personality_evolution_enabled
        and not settings.v21_agent_metrics_enabled
    ):
        violations.append(
            "v21_personality_evolution_enabled 要求 v21_agent_metrics_enabled"
            "（反馈通道先于它反馈的对象上线）"
        )
    if settings.v21_goal_stack_enabled and not settings.v21_agent_runtime_enabled:
        violations.append(
            "v21_goal_stack_enabled 要求 v21_agent_runtime_enabled"
            "（Goal Stack 依赖 Run 阶段插槽）"
        )
    for sub_flag in (
        "v22_emotion_transition_enabled",
        "v22_relationship_addressing_enabled",
        "v22_habit_runtime_enabled",
        "v22_style_contract_enabled",
    ):
        if getattr(settings, sub_flag, False) and not settings.v22_experience_enabled:
            violations.append(
                f"{sub_flag} 要求 v22_experience_enabled（V2.2.0 总闸先开）"
            )
    v23_sub_flags = (
        "v23_time_advance_enabled",
        "v23_daily_life_enabled",
        "v23_event_detection_enabled",
        "v23_scene_expansion_enabled",
        "v23_habit_time_enabled",
        "v23_world_llm_assist_enabled",
        "v23_debug_tick_enabled",
    )
    v23_master = getattr(settings, "v23_world_simulation_enabled", False)
    v23_flags = {flag: getattr(settings, flag, False) for flag in v23_sub_flags}
    for sub_flag, enabled in v23_flags.items():
        if enabled and not v23_master:
            violations.append(
                f"{sub_flag} 要求 v23_world_simulation_enabled（V2.3.0 总闸先开）"
            )
    if v23_flags["v23_daily_life_enabled"] and not v23_flags[
        "v23_time_advance_enabled"
    ]:
        violations.append(
            "v23_daily_life_enabled 要求 v23_time_advance_enabled"
            "（日程依赖日循环标记）"
        )
    if v23_flags["v23_world_llm_assist_enabled"] and not v23_flags[
        "v23_event_detection_enabled"
    ]:
        violations.append(
            "v23_world_llm_assist_enabled 要求 v23_event_detection_enabled"
            "（辅助服务于处境检出）"
        )
    return violations


def v23_reserved_flag_warnings(settings) -> list[str]:
    """RESERVED 子闸被开启时的提示（非阻断）：开了但当前版本无行为分支。"""
    from app.core.settings.world_simulation import RESERVED_V23_SUB_FLAGS

    warnings: list[str] = []
    if not getattr(settings, "v23_world_simulation_enabled", False):
        return warnings
    for flag in RESERVED_V23_SUB_FLAGS:
        if getattr(settings, flag, False):
            warnings.append(
                f"{flag} 为 RESERVED 开关：当前版本尚未接线，开启不会产生行为变化"
            )
    return warnings


def validate_enablement_chain(settings) -> None:
    violations = enablement_violations(settings)
    if violations:
        raise SettingsError("V2 启用链配置错误：" + "；".join(violations))
    for message in v23_reserved_flag_warnings(settings):
        _logger.warning("V2.3.0 开关提示：%s", message)