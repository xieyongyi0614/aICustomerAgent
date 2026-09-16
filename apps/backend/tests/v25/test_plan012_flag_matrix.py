"""PLAN-012 Flag 矩阵一致性：13 Flag 默认值 + 八条串行链 + 总闸 off 三重对照。"""

import hashlib
import json

import pytest

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.core.settings.enablement import (
    V25_DEPENDENCIES,
    V25_GATE_FLAGS,
    V25_SUB_FLAGS,
    enablement_violations,
    validate_enablement_chain,
)
from app.services import goal_arbitration, goal_observation, goal_planning

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
    """U1：13 个 Flag 默认值与 §7.10 逐条一致（12 off + tool_required on）。"""

    def test_defaults_match_the_frozen_table(self):
        settings = get_settings()
        for name, expected in support.V25_DEFAULTS.items():
            assert getattr(settings, name) is expected, name
        assert len(support.V25_FLAG_NAMES) == 13

    def test_parameter_defaults_match_architecture(self):
        settings = get_settings()
        assert settings.v25_plan_max_steps == 5
        assert settings.v25_plan_max_depth == 2
        assert settings.v25_plan_step_max_attempts == 2
        assert settings.v25_plan_revision_budget == 3
        assert settings.v25_plan_ttl_hours == 168
        assert settings.v25_plan_step_cooldown_minutes == 30
        assert settings.v25_plan_replan_min_confidence == 0.7
        assert settings.v25_plan_memory_importance_floor == 0.6


class TestEnablementChainMatrix:
    """U2：八条串行链——非法组合 fail-fast；全链合法组合干净。"""

    def test_default_configuration_is_clean(self):
        assert enablement_violations(get_settings()) == []

    def test_full_chain_is_legal(self, monkeypatch):
        settings = _settings_with(monkeypatch, **support.FULL_CHAIN_ENVS)
        assert enablement_violations(settings) == []

    def test_sub_flag_without_master_fails(self, monkeypatch):
        settings = _settings_with(monkeypatch, V25_PLAN_DEBUG_ENABLED="true")
        reasons = enablement_violations(settings)
        assert any("v25_planning_enabled" in reason or "计划" in reason for reason in reasons)

    def test_master_without_dependencies_fails(self, monkeypatch):
        settings = _settings_with(monkeypatch, V25_PLANNING_ENABLED="true")
        reasons = enablement_violations(settings)
        assert reasons

    def test_execution_requires_scheduler_and_action(self, monkeypatch):
        envs = dict(support.FULL_CHAIN_ENVS)
        envs["V25_PLAN_SCHEDULER_ENABLED"] = "false"
        settings = _settings_with(monkeypatch, **envs)
        reasons = enablement_violations(settings)
        assert reasons

    def test_validate_enablement_chain_raises_readable_error(self, monkeypatch):
        settings = _settings_with(monkeypatch, V25_PLAN_CONTEXT_ENABLED="true")
        with pytest.raises(SettingsError) as excinfo:
            validate_enablement_chain(settings)
        assert excinfo.value.args

    def test_ledger_has_eight_chain_markers_and_records_the_gap(self):
        from app.core.settings import enablement

        docstring = enablement.__doc__
        for marker in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"):
            assert marker in docstring
        assert "七条" in docstring
        assert len(V25_SUB_FLAGS) == 11
        assert V25_GATE_FLAGS[0] == "v25_planning_enabled"
        assert len(V25_DEPENDENCIES) >= 8


class TestAllOffBytewiseCompat:
    """I1 / S6：总闸 off 三重对照——prompt / 原路径 / 维护序列。"""

    def test_existing_gates_stay_closed(self, make_goal):
        goal = make_goal(description="总闸 off 目标")
        assert goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)[
            "status"
        ] == "skipped"
        assert goal_observation.advance_user_goals("plan12-off-user", {}, None)[
            "status"
        ] == "skipped"
        assert goal_arbitration.arbitrate_user("plan12-off-user", None)["status"] == "skipped"

    def test_planning_prompt_bytes_are_unchanged(
        self, make_goal, stub_planning_llm, autonomy_on
    ):
        assert autonomy_on
        recorder: dict = {}
        stub_planning_llm(recorder=recorder)
        goal = make_goal(description="prompt 快照目标", priority=4, domain="relationship")
        assert goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)["status"] == "ok"
        messages = recorder["messages"]
        assert _digest(messages) == FROZEN_PROMPT_DIGEST

    def test_v25_flags_are_all_off_in_this_module_baseline(self):
        settings = get_settings()
        assert settings.v25_planning_enabled is False
        for name in support.V25_FLAG_NAMES:
            if name == "v25_plan_tool_required":
                assert getattr(settings, name) is True
            else:
                assert getattr(settings, name) is False
