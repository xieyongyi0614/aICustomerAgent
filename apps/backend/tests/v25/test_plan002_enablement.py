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

V25_MASTER = "planning_enabled"

V25_SUB_FLAGS = (
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

FULL_CHAIN_ENVS = {
    V25_MASTER: True,
    "plan_context_enabled": True,
    "plan_step_binding_enabled": True,
    "plan_scheduler_enabled": True,
    "plan_execution_enabled": True,
    "plan_observation_enabled": True,
    "plan_revision_enabled": True,
    "plan_memory_enabled": True,
    "plan_reflection_enabled": True,
    "plan_world_feedback_enabled": True,
    "plan_autonomy_enabled": True,
    "plan_debug_enabled": True,
    "agent_runtime_enabled": True,
    "tool_system_enabled": True,
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


def test_u13_the_chain_ledger_has_seven_entries_and_the_module_records_the_gap():
    docstring = enablement.__doc__
    for marker in ("①", "②", "③", "④", "⑤", "⑥", "⑦"):
        assert marker in docstring, marker
    assert "剩余七条" in docstring
    assert len(V25_SUB_FLAGS) == 11
    assert enablement.V25_SUB_FLAGS == V25_SUB_FLAGS
    assert enablement.V25_GATE_FLAGS == (
        enablement.V25_MASTER_FLAG,
        enablement.V25_TOOL_REQUIRED_FLAG,
        *V25_SUB_FLAGS,
    )
    assert len(enablement.V25_DEPENDENCIES) == 6
    sources = {source for source, _, _ in enablement.V25_DEPENDENCIES}
    assert sources == {
        "plan_execution_enabled",
        "plan_step_binding_enabled",
        enablement.V25_TOOL_REQUIRED_FLAG,
        "plan_autonomy_enabled",
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
        "plan_scheduler_enabled",
        "plan_step_binding_enabled",
    }
    assert cross_version == {
        "action_enabled",
        "tool_system_enabled",
        "agent_runtime_enabled",
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


def test_u13_execution_requires_the_scheduler_sub_gate(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "plan_tool_required": False,
            "plan_execution_enabled": True,
            "action_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("plan_scheduler_enabled" in item for item in violations)


def test_u13_execution_requires_the_action_engine(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "plan_tool_required": False,
            "plan_execution_enabled": True,
            "plan_scheduler_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("action_enabled" in item for item in violations)


def test_u13_step_binding_requires_the_tool_system(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "plan_step_binding_enabled": True,
            "plan_tool_required": False,
        },
    )
    violations = enablement_violations(settings)
    assert any("tool_system_enabled" in item for item in violations)


def test_u13_tool_required_requires_binding_and_the_tool_system(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
        },
    )
    violations = enablement_violations(settings)
    assert any("plan_step_binding_enabled" in item for item in violations)
    assert any("tool_system_enabled" in item for item in violations)


def test_u13_tool_required_is_inert_while_the_master_is_off(monkeypatch):
    settings = _settings_with(monkeypatch, **{"plan_tool_required": True})
    assert settings.plan_tool_required is True
    assert settings.planning_enabled is False
    assert enablement_violations(settings) == []


def test_u13_autonomy_requires_the_agent_runtime(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        **{
            V25_MASTER: True,
            "plan_tool_required": False,
            "plan_autonomy_enabled": True,
        },
    )
    violations = enablement_violations(settings)
    assert any("agent_runtime_enabled" in item for item in violations)


def test_u13_all_v25_flags_with_their_dependencies_are_clean(monkeypatch):
    settings = _settings_with(monkeypatch, **FULL_CHAIN_ENVS)
    assert enablement_violations(settings) == []


def test_u13_disabling_tool_required_allows_headless_planning(monkeypatch):
    envs = dict(FULL_CHAIN_ENVS)
    envs["plan_tool_required"] = False
    envs["tool_system_enabled"] = False
    envs["plan_step_binding_enabled"] = False
    settings = _settings_with(monkeypatch, **envs)
    assert enablement_violations(settings) == []


def test_i2_default_settings_pass_the_chain():
    validate_enablement_chain(get_settings())


def test_i2_violation_message_is_readable_chinese(monkeypatch):
    settings = _settings_with(monkeypatch, **{"plan_debug_enabled": True})
    with pytest.raises(SettingsError) as excinfo:
        validate_enablement_chain(settings)
    message = str(excinfo.value)
    assert "V2 启用链配置错误" in message
    assert "plan_debug_enabled" in message
    assert "总闸" in message


def test_existing_v2_v21_v23_v24_chain_rules_intact(monkeypatch):
    settings = _settings_with(monkeypatch, goal_stack_enabled=True)
    assert any(
        "agent_runtime_enabled" in item for item in enablement_violations(settings)
    )

    settings = _settings_with(monkeypatch, event_detection_enabled=True)
    assert any(
        "world_simulation_enabled" in item for item in enablement_violations(settings)
    )

    settings = _settings_with(monkeypatch, tool_surface_enabled=True)
    assert any(
        "tool_system_enabled" in item for item in enablement_violations(settings)
    )
