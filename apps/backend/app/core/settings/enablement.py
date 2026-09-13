"""V2.0.0 Enablement 串行链校验（dependency-graph 串行链的部署时 fail-fast）。

规则（docs/version/v2.0.0/architecture/dependency-graph.md §1 + phase-6 附录）：
- v2_autonomy_advanced_enabled 依赖 v2_life_loop_enabled 且 action_enabled（Sub-Goal
  执行经 outbox + Life Loop 消费 + V9 行动总闸）。
- v2_action_outbox_enabled 依赖 v2_life_loop_enabled（无消费器的 outbox 会死信堆积）。

仅在启动边界调用（main.lifespan / 运维脚本），不做为模型级校验，
以保留子域隔离单测使用部分 Flag 组合的自由度。
"""

from app.core.settings._shared import SettingsError


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
    if settings.v21_goal_stack_enabled and not settings.v21_agent_runtime_enabled:
        violations.append(
            "v21_goal_stack_enabled 要求 v21_agent_runtime_enabled"
            "（Goal Stack 依赖 Run 阶段插槽）"
        )
    return violations


def validate_enablement_chain(settings) -> None:
    violations = enablement_violations(settings)
    if violations:
        raise SettingsError("V2 启用链配置错误：" + "；".join(violations))