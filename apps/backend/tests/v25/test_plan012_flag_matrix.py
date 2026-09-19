"""PLAN-012 Flag 矩阵一致性（v25 去门控语义反转）：2 策略位默认值 + 链机制仍被 v26 段行使 + 常开 prompt 快照。

原「13 Flag 默认值 + 八条串行链 + 总闸 off 对照」三重矩阵的前提已随
`vXX_` 开关体系删除：编排恒常开，本模块按范围标记纪律显式更新——
默认值矩阵收敛为保留的两个策略位；串行链矩阵改以 V2.6.0 段样本负例钉住
链机制本身；「总闸 off prompt 逐字节不变」反转为「常开路径 prompt 快照」。
"""

import pytest

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.core.settings.enablement import enablement_violations, validate_enablement_chain
from app.services import goal_planning

from . import plan012_support as support
from .test_plan001_flag_regression import FROZEN_PROMPT_DIGEST, _digest


def _settings_with(monkeypatch, **envs):
    for key, value in envs.items():
        text = str(value).lower() if isinstance(value, bool) else str(value)
        monkeypatch.setenv(key.upper(), text)
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


class TestFlagDefaults:
    """U1：2 个策略位默认值与 §7.10 逐条一致（均 on；门控 Flag 已删）。"""

    def test_defaults_match_the_frozen_table(self):
        settings = get_settings()
        for name, expected in support.V25_DEFAULTS.items():
            assert getattr(settings, name) is expected, name
        assert len(support.V25_FLAG_NAMES) == 2

    def test_parameter_defaults_match_architecture(self):
        settings = get_settings()
        assert settings.plan_max_steps == 5
        assert settings.plan_max_depth == 2
        assert settings.plan_step_max_attempts == 2
        assert settings.plan_revision_budget == 3
        assert settings.plan_ttl_hours == 168
        assert settings.plan_step_cooldown_minutes == 30
        assert settings.plan_replan_min_confidence == 0.7
        assert settings.plan_memory_importance_floor == 0.6


class TestEnablementChainMatrix:
    """U2 语义反转（批次 7 收口）：V2.6.0 段亦已删除，enablement 只剩空实现——
    任何组合零违规；链账本常量（V25_* / V26_*）全部消失。"""

    def test_default_configuration_is_clean(self):
        assert enablement_violations(get_settings()) == []

    def test_full_chain_is_legal(self, monkeypatch):
        settings = _settings_with(monkeypatch, **support.FULL_CHAIN_ENVS)
        assert enablement_violations(settings) == []

    def test_legacy_chain_violation_samples_are_all_clean(self):
        """原各段负例样本（子闸无总闸 / 总闸无基闸）在新实现下零违规。"""
        from types import SimpleNamespace

        stub = SimpleNamespace(
            action_execution_enabled=False,
            action_scheduler_enabled=True,
            action_enabled=False,
            planning_enabled=True,
        )
        assert enablement_violations(stub) == []

    def test_validate_enablement_chain_never_raises(self):
        from types import SimpleNamespace

        validate_enablement_chain(SimpleNamespace())

    def test_ledger_has_no_chain_markers(self):
        from app.core.settings import enablement

        docstring = enablement.__doc__ or ""
        assert "V2.0.0 ~ V2.6.0 段" in docstring and "已整体移除" in docstring
        assert not any(
            name.startswith(("V25_", "V26_")) for name in vars(enablement)
        )


class TestAlwaysOnPlanningCompat:
    """I1 / S6 语义反转：编排常开对照——prompt 快照与策略位默认值。"""

    def test_planning_prompt_digest_is_stable(
        self, make_goal, stub_planning_llm, autonomy_on
    ):
        assert autonomy_on
        recorder: dict = {}
        stub_planning_llm(recorder=recorder)
        goal = make_goal(description="prompt 快照目标", priority=4, domain="relationship")
        assert goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)["status"] == "ok"
        messages = recorder["messages"]
        assert _digest(messages) == FROZEN_PROMPT_DIGEST

    def test_removed_gates_are_absent_and_policy_bits_default_on(self):
        from app.core.settings import Settings

        settings = get_settings()
        for name in support.V25_FLAG_NAMES:
            assert getattr(settings, name) is True, name
        for name in (
            "planning_enabled",
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
        ):
            assert name not in Settings.model_fields, name
