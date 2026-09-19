"""PLAN-002 U13 / I2 / S4：v25 串行链校验的**语义反转**（v25 去门控收口）。

原 v25 链（总闸 + 11 子闸 + 3 条依赖）已随 `vXX_` 开关体系整段删除：
编排恒常开，`enablement.py` 只剩 V2.6.0 段。本模块按范围标记纪律显式更新——
原 U13 各负例的前提（子闸可关）已不存在，整体退役；保留两类仍有意义的断言：
默认配置必须过链（I2），以及链机制本身仍被 V2.6.0 段行使（以 v26 样本负例钉住）。
"""

import pytest

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.core.settings import enablement
from app.core.settings.enablement import (
    enablement_violations,
    validate_enablement_chain,
)

REMOVED_V25_GATE_FLAGS = (
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
)

FULL_CHAIN_ENVS = {
    "PLAN_TOOL_REQUIRED": "true",
    "ACTION_ENABLED": "true",
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


def test_u13_v25_chain_ledger_is_gone_from_the_module():
    """v25 段整段删除：链账本常量与判定都不再引用任何 plan_* Flag。"""
    for name in (
        "V25_MASTER_FLAG",
        "V25_TOOL_REQUIRED_FLAG",
        "V25_SUB_FLAGS",
        "V25_GATE_FLAGS",
        "V25_DEPENDENCIES",
    ):
        assert not hasattr(enablement, name), name
    docstring = enablement.__doc__ or ""
    assert "V2.5.0 段" in docstring and "已整体移除" in docstring


def test_u13_removed_flags_never_produce_violations(monkeypatch):
    """已删 Flag 的遗留 env 键被 `extra="ignore"` 静默吞掉，不得产生任何违规。"""
    for flag in REMOVED_V25_GATE_FLAGS:
        settings = _settings_with(monkeypatch, **{flag.upper(): "true"})
        assert enablement_violations(settings) == [], flag


def test_u13_full_chain_is_clean(monkeypatch):
    settings = _settings_with(monkeypatch, **FULL_CHAIN_ENVS)
    assert enablement_violations(settings) == []


def test_i2_default_settings_pass_the_chain():
    validate_enablement_chain(get_settings())


def test_i2_violation_message_is_readable_chinese(monkeypatch):
    """链机制仍被行使：v26 样本负例（子闸无总闸）在 Settings 构造期即报可读错误。"""
    from types import SimpleNamespace

    with pytest.raises(SettingsError) as excinfo:
        _settings_with(monkeypatch, **{"action_scheduler_enabled": True})
    message = str(excinfo.value)
    assert "action_scheduler_enabled" in message
    assert "总闸" in message

    stub = SimpleNamespace(
        action_execution_enabled=False,
        action_scheduler_enabled=True,
        action_enabled=True,
    )
    with pytest.raises(SettingsError) as chain_exc:
        validate_enablement_chain(stub)
    assert "V2 启用链配置错误" in str(chain_exc.value)


def test_v25_chain_rules_are_gone(monkeypatch):
    """v25 段连同 `planning_enabled` 一并从链上消失：任何组合都不再报 plan_* 依赖。"""
    for envs in ({}, FULL_CHAIN_ENVS):
        settings = _settings_with(monkeypatch, **envs)
        violations = enablement_violations(settings)
        assert not any("plan_" in item for item in violations)


@pytest.mark.parametrize("flag", REMOVED_V25_GATE_FLAGS)
def test_u13_removed_flags_are_absent_from_settings(flag):
    from app.core.settings import Settings

    assert flag not in Settings.model_fields
