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
    """U2：链机制仍被 V2.6.0 段行使——非法组合 fail-fast；全链合法组合干净。"""

    def test_default_configuration_is_clean(self):
        assert enablement_violations(get_settings()) == []

    def test_full_chain_is_legal(self, monkeypatch):
        settings = _settings_with(monkeypatch, **support.FULL_CHAIN_ENVS)
        assert enablement_violations(settings) == []

    def test_v26_sub_flag_without_master_fails(self, monkeypatch):
        """v26 链在 Settings 构造期即 fail-fast（model 级校验）。"""
        with pytest.raises(SettingsError) as excinfo:
            _settings_with(monkeypatch, ACTION_SCHEDULER_ENABLED="true")
        assert "action_scheduler_enabled" in str(excinfo.value)
        assert "action_execution_enabled" in str(excinfo.value)

    def test_v26_master_without_base_gate_fails(self):
        """总闸 ⇒ 基闸 `action_enabled` 由 enablement 层判定（model 级校验只管子闸）。"""
        from types import SimpleNamespace

        stub = SimpleNamespace(
            action_execution_enabled=True,
            action_scheduler_enabled=False,
            action_enabled=False,
        )
        reasons = enablement_violations(stub)
        assert any("action_enabled" in reason for reason in reasons)

    def test_enablement_violations_reports_the_v26_chain(self):
        """`enablement_violations` 对 v26 组合仍可独立判定（打桩 Settings）。"""
        from types import SimpleNamespace

        stub = SimpleNamespace(
            action_execution_enabled=False,
            action_scheduler_enabled=True,
            action_enabled=True,
        )
        reasons = enablement_violations(stub)
        assert any("action_execution_enabled" in reason for reason in reasons)

    def test_validate_enablement_chain_raises_readable_error(self):
        """`validate_enablement_chain` 对链上违规组合抛可读 SettingsError（打桩 Settings）。"""
        from types import SimpleNamespace

        stub = SimpleNamespace(
            action_execution_enabled=False,
            action_scheduler_enabled=True,
            action_enabled=True,
        )
        with pytest.raises(SettingsError) as excinfo:
            validate_enablement_chain(stub)
        assert excinfo.value.args

    def test_ledger_has_v26_chain_markers_only(self):
        from app.core.settings import enablement

        docstring = enablement.__doc__ or ""
        for marker in ("①", "②"):
            assert marker in docstring
        assert "V2.5.0 段" in docstring and "已整体移除" in docstring
        assert not any(
            name.startswith("V25_") for name in vars(enablement)
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
