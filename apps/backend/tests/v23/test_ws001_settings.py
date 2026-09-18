"""WS-001：V2.3.0 Flag 体系与模拟参数测试。"""

import json

import pytest

from app.core.settings import get_settings
from app.core.settings.enablement import enablement_violations, validate_enablement_chain
from app.core.settings._shared import SettingsError

V23_FLAGS = (
    "world_simulation_enabled",
    "time_advance_enabled",
    "daily_life_enabled",
    "event_detection_enabled",
    "scene_expansion_enabled",
    "habit_time_enabled",
    "world_llm_assist_enabled",
    "debug_tick_enabled",
)

V23_PARAM_DEFAULTS = {
    "world_sim_interval_seconds": 60,
    "sim_advance_max_minutes": 120,
    "world_event_tick_cap": 8,
    "catch_up_max_days": 7,
    "world_brief_char_budget": 400,
    "world_context_char_budget_v23": 1000,
    "daily_plan_retention_days": 30,
    "user_situation_valid_hours": 48,
    "world_llm_assist_sample_rate": 0.2,
    "interest_confidence_threshold": 0.7,
}


def _settings_with(monkeypatch, **envs):
    for key, value in envs.items():
        monkeypatch.setenv(key.upper(), str(value).lower() if isinstance(value, bool) else str(value))
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def test_v23_flags_default_off():
    settings = get_settings()
    for flag in V23_FLAGS:
        assert getattr(settings, flag) is False, flag


def test_v23_params_defaults():
    settings = get_settings()
    for name, value in V23_PARAM_DEFAULTS.items():
        assert getattr(settings, name) == value, name
    boundaries = json.loads(settings.part_boundaries_json)
    assert boundaries == {
        "morning": 360,
        "noon": 690,
        "afternoon": 840,
        "evening": 1080,
        "night": 1320,
    }
    assert settings.world_event_escalation_types.split(",") == [
        "user_condition",
        "weather_change",
        "calendar_event",
        "goal_completed",
    ]


def test_sub_flag_without_master_is_violation(monkeypatch):
    for flag in V23_FLAGS:
        if flag == "world_simulation_enabled":
            continue
        settings = _settings_with(monkeypatch, **{flag: True})
        violations = enablement_violations(settings)
        assert any("world_simulation_enabled" in v for v in violations), flag


def test_all_sub_flags_with_master_is_clean(monkeypatch):
    envs = {flag: True for flag in V23_FLAGS}
    settings = _settings_with(monkeypatch, **envs)
    assert enablement_violations(settings) == []


def test_daily_life_requires_time_advance(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        world_simulation_enabled=True,
        daily_life_enabled=True,
    )
    violations = enablement_violations(settings)
    assert any("time_advance_enabled" in v for v in violations)


def test_llm_assist_requires_event_detection(monkeypatch):
    settings = _settings_with(
        monkeypatch,
        world_simulation_enabled=True,
        world_llm_assist_enabled=True,
    )
    violations = enablement_violations(settings)
    assert any("event_detection_enabled" in v for v in violations)


def test_validate_chain_raises_on_violation(monkeypatch):
    settings = _settings_with(monkeypatch, daily_life_enabled=True)
    with pytest.raises(SettingsError):
        validate_enablement_chain(settings)


def test_default_settings_pass_chain():
    validate_enablement_chain(get_settings())
