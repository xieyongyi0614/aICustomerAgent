"""TOOL-001：ToolSettings Flag 体系、参数与 csv 解析（TOOL-001 §4.3 / §6 / E6 / E7 / E10）。"""

import pytest

from app.core.settings import get_settings
from app.core.settings._shared import SettingsError
from app.core.settings.tool import ToolSettings

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

V24_PARAM_DEFAULTS = {
    "tool_disabled_ids": "",
    "tool_surface_max_tools": 12,
    "tool_breaker_threshold": 3,
    "tool_breaker_cooldown_seconds": 300,
    "tool_confirm_timeout_hours": 24,
    "tool_confirm_ttl_reuse": True,
    "tool_audit_retention_days": 180,
    "tool_ext_manifest_path": "",
    "tool_ext_allowed_hosts": "",
}


def test_v24_flags_default_off():
    settings = get_settings()
    assert len(V24_FLAGS) == 10
    for flag in V24_FLAGS:
        assert getattr(settings, flag) is False, flag


def test_v24_params_defaults():
    settings = get_settings()
    assert len(V24_PARAM_DEFAULTS) == 9
    for name, value in V24_PARAM_DEFAULTS.items():
        assert getattr(settings, name) == value, name


def test_tool_settings_merged_into_global_settings():
    settings = get_settings()
    assert isinstance(settings, ToolSettings)
    assert settings.tool_surface_max_tools == 12


def test_tool_settings_reads_from_environment(monkeypatch):
    monkeypatch.setenv("TOOL_SYSTEM_ENABLED", "true")
    monkeypatch.setenv("TOOL_SURFACE_MAX_TOOLS", "7")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.tool_system_enabled is True
        assert settings.tool_surface_max_tools == 7
    finally:
        get_settings.cache_clear()


def test_e10_disabled_tool_ids_returns_empty_set_with_all_flags_off():
    settings = get_settings()
    assert settings.tool_system_enabled is False
    assert settings.disabled_tool_ids() == frozenset()
    assert settings.allowed_ext_hosts() == frozenset()


def test_e7_disabled_tool_ids_strips_blank_and_dedupes():
    settings = ToolSettings(
        tool_disabled_ids=" builtin.reminder.create ,builtin.reminder.create,, "
        "world.obj.move ,\t"
    )
    assert settings.disabled_tool_ids() == frozenset(
        {"builtin.reminder.create", "world.obj.move"}
    )


def test_e7_unregistered_tool_ids_are_not_rejected():
    settings = ToolSettings(tool_disabled_ids="not.a.registered.tool,ghost.ns.act")
    assert settings.disabled_tool_ids() == frozenset(
        {"not.a.registered.tool", "ghost.ns.act"}
    )


def test_allowed_ext_hosts_strips_blank_and_dedupes():
    settings = ToolSettings(
        tool_ext_allowed_hosts=" api.example.com , cdn.example.com ,api.example.com, "
    )
    assert settings.allowed_ext_hosts() == frozenset(
        {"api.example.com", "cdn.example.com"}
    )


def test_empty_csv_yields_empty_set():
    settings = ToolSettings()
    assert settings.disabled_tool_ids() == frozenset()
    assert settings.allowed_ext_hosts() == frozenset()


@pytest.mark.parametrize("value", [0, -1, -12])
def test_e6_surface_max_tools_below_one_fails_fast(value):
    with pytest.raises(SettingsError) as excinfo:
        ToolSettings(tool_surface_max_tools=value)
    assert "TOOL_SURFACE_MAX_TOOLS" in str(excinfo.value)


@pytest.mark.parametrize(
    "field_name",
    [
        "tool_breaker_threshold",
        "tool_breaker_cooldown_seconds",
        "tool_confirm_timeout_hours",
        "tool_audit_retention_days",
    ],
)
@pytest.mark.parametrize("value", [0, -5])
def test_positive_params_fail_fast(field_name, value):
    with pytest.raises(SettingsError) as excinfo:
        ToolSettings(**{field_name: value})
    assert field_name.upper() in str(excinfo.value)


def test_boundary_values_accepted():
    settings = ToolSettings(
        tool_surface_max_tools=1,
        tool_breaker_threshold=1,
        tool_breaker_cooldown_seconds=1,
        tool_confirm_timeout_hours=1,
        tool_audit_retention_days=1,
    )
    assert settings.tool_surface_max_tools == 1
    assert settings.tool_confirm_ttl_reuse is True
