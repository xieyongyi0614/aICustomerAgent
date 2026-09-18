"""WS-001：World Simulation 调参与 enablement 现状（开关已固化删除）。"""

import json

import pytest

from app.core.settings import get_settings
from app.core.settings.enablement import enablement_violations, validate_enablement_chain
from app.core.settings._shared import SettingsError
from app.core.settings import Settings

V23_REMOVED_FLAGS = (
    "world_simulation_enabled",
    "time_advance_enabled",
    "daily_life_enabled",
    "event_detection_enabled",
    "scene_expansion_enabled",
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


def test_v23_flags_removed_from_settings():
    for flag in V23_REMOVED_FLAGS:
        assert flag not in Settings.model_fields, flag


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


def test_no_v23_enablement_rules_remain():
    settings = get_settings()
    violations = enablement_violations(settings)
    assert not any(
        token in v
        for v in violations
        for token in (
            "world_simulation_enabled",
            "time_advance_enabled",
            "daily_life_enabled",
            "event_detection_enabled",
            "world_llm_assist_enabled",
            "scene_expansion_enabled",
            "debug_tick_enabled",
        )
    )


def test_default_settings_pass_chain():
    validate_enablement_chain(get_settings())
