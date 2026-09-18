"""TOOL-001：v24 串行链校验（architecture.md §7.8 / TOOL-001 §6.2）。"""

import pytest

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.core.settings.enablement import enablement_violations, validate_enablement_chain

V24_FLAGS = (
    "tool_system_enabled",
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

V24_SUB_FLAGS = V24_FLAGS[1:]

FEISHU_BINDING_ENVS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_test",
    "feishu_app_secret": "test_secret",
    "feishu_verification_token": "test_token",
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


@pytest.mark.parametrize("flag", V24_SUB_FLAGS)
def test_each_v24_sub_flag_without_master_is_violation(monkeypatch, flag):
    settings = _settings_with(monkeypatch, **{flag: True})
    violations = enablement_violations(settings)
    assert any("tool_system_enabled" in violation for violation in violations), flag


@pytest.mark.parametrize("flag", V24_SUB_FLAGS)
def test_validate_chain_fail_fast_per_sub_flag(monkeypatch, flag):
    settings = _settings_with(monkeypatch, **{flag: True})
    with pytest.raises(SettingsError) as excinfo:
        validate_enablement_chain(settings)
    assert flag in str(excinfo.value)


def test_all_v24_flags_with_master_is_clean(monkeypatch):
    envs = {flag: True for flag in V24_FLAGS}
    envs.update(FEISHU_BINDING_ENVS)
    settings = _settings_with(monkeypatch, **envs)
    assert enablement_violations(settings) == []


def test_channel_requires_feishu_binding(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        tool_system_enabled=True,
        tool_channel_enabled=True,
    )
    violations = enablement_violations(settings)
    assert any("feishu_enabled" in violation for violation in violations)


def test_channel_with_feishu_binding_is_clean(monkeypatch):
    envs = dict(FEISHU_BINDING_ENVS)
    envs.update(tool_system_enabled=True, tool_channel_enabled=True)
    settings = _settings_with(monkeypatch, **envs)
    assert enablement_violations(settings) == []


def test_external_api_requires_master(monkeypatch):
    settings = _settings_with(monkeypatch, tool_external_api_enabled=True)
    violations = enablement_violations(settings)
    assert any("tool_system_enabled" in violation for violation in violations)


def test_violation_message_is_readable_chinese(monkeypatch):
    settings = _settings_with(monkeypatch, tool_permission_enabled=True)
    with pytest.raises(SettingsError) as excinfo:
        validate_enablement_chain(settings)
    message = str(excinfo.value)
    assert "V2 启用链配置错误" in message
    assert "tool_permission_enabled" in message
    assert "总闸" in message


def test_default_settings_pass_chain():
    validate_enablement_chain(get_settings())


def test_existing_v24_chain_rules_intact(monkeypatch):
    settings = _settings_with(monkeypatch, tool_channel_enabled=True)
    assert any("feishu_enabled" in v for v in enablement_violations(settings))
