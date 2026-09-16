"""PLAN-002 U13 / I2 / S4：v25 串行链校验（architecture.md §7.10 八条）。

每条链一个违规负例，逐条命中并报出违规链；默认配置必须干净（否则进程默认启动即失败）。
"""

import pytest

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.core.settings import enablement
from app.core.settings.enablement import (
    enablement_violations,
    validate_enablement_chain,
)

V25_MASTER = "v25_planning_enabled"

V25_SUB_FLAGS = (
    "v25_plan_context_enabled",
    "v25_plan_step_binding_enabled",
    "v25_plan_scheduler_enabled",
    "v25_plan_execution_enabled",
    "v25_plan_observation_enabled",
    "v25_plan_revision_enabled",
    "v25_plan_memory_enabled",
    "v25_plan_reflection_enabled",
    "v25_plan_world_feedback_enabled",
    "v25_plan_autonomy_enabled",
    "v25_plan_debug_enabled",
)

FULL_CHAIN_ENVS = {
    V25_MASTER: True,
    "v25_plan_context_enabled": True,
    "v25_plan_step_binding_enabled": True,
    "v25_plan_scheduler_enabled": True,
    "v25_plan_execution_enabled": True,
    "v25_plan_observation_enabled": True,
    "v25_plan_revision_enabled": True,
    "v25_plan_memory_enabled": True,
    "v25_plan_reflection_enabled": True,
    "v25_plan_world_feedback_enabled": True,
    "v25_plan_autonomy_enabled": True,
    "v25_plan_debug_enabled": True,
    "v2_autonomy_advanced_enabled": True,
    "v2_life_loop_enabled": True,
    "v2_memory_enabled": True,
    "v2_reflection_enabled": True,
    "v21_agent_runtime_enabled": True,
    "v24_tool_system_enabled": True,
    "action_enabled": True,
}


def _settings_with(monkeypatch, **envs):
    for key, value in envs.items():
        text = str(value).lower() if isinstance(value, bool) else str(value)
        monkeypatch.setenv(key.upper(), text)
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def test_u13_the_chain_ledger_has_eight_entries_and_the_module_records_the_gap():
    docstring = enablement.__doc__
    for marker in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"):
        assert marker in docstring, marker
    assert "八条" in docstring
    assert "七条串行链" in docstring
    assert len(V25_SUB_FLAGS) == 11
    assert enablement.V25_SUB_FLAGS == V25_SUB_FLAGS
    assert enablement.V25_GATE_FLAGS == (
        enablement.V25_MASTER_FLAG,
        enablement.V25_TOOL_REQUIRED_FLAG,
        *V25_SUB_FLAGS,
    )
    assert len(enablement.V25_DEPENDENCIES) == 10
    sources = {source for source, _, _ in enablement.V25_DEPENDENCIES}
    assert sources == {
        enablement.V25_MASTER_FLAG,
        "v25_plan_execution_enabled",
        "v25_plan_step_binding_enabled",
        enablement.V25_TOOL_REQUIRED_FLAG,
        "v25_plan_reflection_enabled",
        "v25_plan_memory_enabled",
        "v25_plan_autonomy_enabled",
    }
    intra_version = {
        dependency
        for _, dependency, _ in enablement.V25_DEPENDENCIES
        if dependency in enablement.V25_GATE_FLAGS
    }
    cross_version = {
        dependency
        for _, dependency, _ in enablement.V25_DEPENDENCIES
        if dependency not in enablement.V25_GATE_FLAGS
    }
    assert intra_version == {
        "v25_plan_scheduler_enabled",
        "v25_plan_step_binding_enabled",
    }
    assert cross_version == {
        "v2_autonomy_advanced_enabled",
        "v2_life_loop_enabled",
        "action_enabled",
        "v24_tool_system_enabled",
        "v2_reflection_enabled",
        "v2_memory_enabled",
        "v21_agent_runtime_enabled",
    }
    for _, _, reason in enablement.V25_DEPENDENCIES:
        assert reason.startswith("（") and reason.endswith("）")


@pytest.mark.parametrize("flag", V25_SUB_FLAGS)
def test_u13_each_v25_sub_flag_without_master_is_a_violation(monkeypatch, flag):
    settings = _settings_with(monkeypatch, **{flag: True})
    violations = enablement_violations(settings)
    assert any(V25_MASTER in violation for violation in violations), flag
    assert any(flag in violation for violation in violations), flag


@pytest.mark.parametrize("flag", V25_SUB_FLAGS)
def test_u13_validate_chain_fail_fast_per_v25_sub_flag(monkeypatch, flag):
    settings = _settings_with(monkeypatch, **{flag: True})
    with pytest.raises(SettingsError) as excinfo:
        validate_enablement_chain(settings)
    message = str(excinfo.value)
    assert "V2 启用链配置错误" in message
    assert flag in message


def test_u13_master_requires_the_autonomy_advanced_flag(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{V25_MASTER: True, "v25_plan_tool_required": False, "v2_life_loop_enabled": True},
    )
    violations = enablement_violations(settings)
    assert any("v2_autonomy_advanced_enabled" in item for item in violations)


def test_u13_master_requires_the_life_loop(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v25_plan_tool_required": False,
            "v2_autonomy_advanced_enabled": True,
            "action_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("v2_life_loop_enabled" in item for item in violations)


def test_u13_execution_requires_the_scheduler_sub_gate(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v25_plan_tool_required": False,
            "v25_plan_execution_enabled": True,
            "action_enabled": True,
            "v2_autonomy_advanced_enabled": True,
            "v2_life_loop_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("v25_plan_scheduler_enabled" in item for item in violations)


def test_u13_execution_requires_the_action_engine(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v25_plan_tool_required": False,
            "v25_plan_execution_enabled": True,
            "v25_plan_scheduler_enabled": True,
            "v2_autonomy_advanced_enabled": True,
            "v2_life_loop_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("action_enabled" in item for item in violations)


def test_u13_step_binding_requires_the_tool_system(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v25_plan_step_binding_enabled": True,
            "v25_plan_tool_required": False,
            "v2_autonomy_advanced_enabled": True,
            "v2_life_loop_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("v24_tool_system_enabled" in item for item in violations)


def test_u13_tool_required_requires_binding_and_the_tool_system(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v2_autonomy_advanced_enabled": True,
            "v2_life_loop_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("v25_plan_step_binding_enabled" in item for item in violations)
    assert any("v24_tool_system_enabled" in item for item in violations)


def test_u13_tool_required_is_inert_while_the_master_is_off(monkeypatch):
    settings = _settings_with(monkeypatch, **{"v25_plan_tool_required": True})
    assert settings.v25_plan_tool_required is True
    assert settings.v25_planning_enabled is False
    assert enablement_violations(settings) == []


def test_u13_reflection_requires_the_reflection_master(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v25_plan_tool_required": False,
            "v25_plan_reflection_enabled": True,
            "v2_autonomy_advanced_enabled": True,
            "v2_life_loop_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("v2_reflection_enabled" in item for item in violations)


def test_u13_memory_requires_the_memory_master(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v25_plan_tool_required": False,
            "v25_plan_memory_enabled": True,
            "v2_autonomy_advanced_enabled": True,
            "v2_life_loop_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("v2_memory_enabled" in item for item in violations)


def test_u13_autonomy_requires_the_agent_runtime(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "v25_plan_tool_required": False,
            "v25_plan_autonomy_enabled": True,
            "v2_autonomy_advanced_enabled": True,
            "v2_life_loop_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("v21_agent_runtime_enabled" in item for item in violations)


def test_u13_all_v25_flags_with_their_dependencies_are_clean(monkeypatch):
    settings = _settings_with(monkeypatch, **FULL_CHAIN_ENVS)
    assert enablement_violations(settings) == []


def test_u13_disabling_tool_required_allows_headless_planning(monkeypatch):
    envs = dict(FULL_CHAIN_ENVS)
    envs["v25_plan_tool_required"] = False
    envs["v24_tool_system_enabled"] = False
    envs["v25_plan_step_binding_enabled"] = False
    settings = _settings_with(monkeypatch, **envs)
    assert enablement_violations(settings) == []


def test_i2_default_settings_pass_the_chain():
    validate_enablement_chain(get_settings())


def test_i2_violation_message_is_readable_chinese(monkeypatch):
    settings = _settings_with(monkeypatch, **{"v25_plan_debug_enabled": True})
    with pytest.raises(SettingsError) as excinfo:
        validate_enablement_chain(settings)
    message = str(excinfo.value)
    assert "V2 启用链配置错误" in message
    assert "v25_plan_debug_enabled" in message
    assert "总闸" in message


def test_existing_v2_v21_v23_v24_chain_rules_intact(monkeypatch):
    settings = _settings_with(monkeypatch, v2_autonomy_advanced_enabled=True)
    assert any("v2_life_loop_enabled" in item for item in enablement_violations(settings))

    settings = _settings_with(monkeypatch, v21_goal_stack_enabled=True)
    assert any(
        "v21_agent_runtime_enabled" in item for item in enablement_violations(settings)
    )

    settings = _settings_with(monkeypatch, v23_event_detection_enabled=True)
    assert any(
        "v23_world_simulation_enabled" in item for item in enablement_violations(settings)
    )

    settings = _settings_with(monkeypatch, v24_tool_surface_enabled=True)
    assert any(
        "v24_tool_system_enabled" in item for item in enablement_violations(settings)
    )
