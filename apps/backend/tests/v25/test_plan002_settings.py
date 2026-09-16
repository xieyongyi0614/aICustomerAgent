"""PLAN-002 U6 / U12 / I1：`PlanSettings` 的 13 Flag、14 参数默认值与参数自校验。

默认值逐条写死（Task Detail §4.5.1 / §4.5.2），源码与表的任何差异即失败。
"""

import pytest

from app.core.settings import Settings, get_settings
from app.core.settings._shared import SettingsError
from app.core.settings.plan import PlanSettings

V25_FLAG_DEFAULTS = {
    "v25_planning_enabled": False,
    "v25_plan_context_enabled": False,
    "v25_plan_step_binding_enabled": False,
    "v25_plan_scheduler_enabled": False,
    "v25_plan_execution_enabled": False,
    "v25_plan_observation_enabled": False,
    "v25_plan_revision_enabled": False,
    "v25_plan_memory_enabled": False,
    "v25_plan_reflection_enabled": False,
    "v25_plan_world_feedback_enabled": False,
    "v25_plan_autonomy_enabled": False,
    "v25_plan_tool_required": True,
    "v25_plan_debug_enabled": False,
}

V25_PARAM_DEFAULTS = {
    "v25_plan_max_steps": 5,
    "v25_plan_max_depth": 2,
    "v25_plan_step_max_attempts": 2,
    "v25_plan_revision_budget": 3,
    "v25_plan_ttl_hours": 168,
    "v25_plan_step_cooldown_minutes": 30,
    "v25_plan_observation_window_minutes": 120,
    "v25_plan_context_memory_limit": 5,
    "v25_plan_context_insight_limit": 5,
    "v25_plan_llm_profile": "",
    "v25_plan_replan_min_confidence": 0.7,
    "v25_plan_reflection_min_samples": 3,
    "v25_plan_memory_importance_floor": 0.6,
    "v25_plan_context_digest_enabled": True,
}

POSITIVE_PARAM_CONSTRAINTS = (
    "v25_plan_max_steps",
    "v25_plan_max_depth",
    "v25_plan_step_max_attempts",
    "v25_plan_ttl_hours",
    "v25_plan_observation_window_minutes",
    "v25_plan_reflection_min_samples",
)

NON_NEGATIVE_PARAM_CONSTRAINTS = (
    "v25_plan_revision_budget",
    "v25_plan_step_cooldown_minutes",
    "v25_plan_context_memory_limit",
    "v25_plan_context_insight_limit",
)

UNIT_INTERVAL_PARAM_CONSTRAINTS = (
    "v25_plan_replan_min_confidence",
    "v25_plan_memory_importance_floor",
)


CONSTRAINED_PARAMS = (
    POSITIVE_PARAM_CONSTRAINTS
    + NON_NEGATIVE_PARAM_CONSTRAINTS
    + UNIT_INTERVAL_PARAM_CONSTRAINTS
)

UNCONSTRAINED_PARAMS = ("v25_plan_llm_profile", "v25_plan_context_digest_enabled")


def test_u6_plan_settings_declares_thirteen_flags_and_fourteen_params():
    assert len(V25_FLAG_DEFAULTS) == 13
    assert len(V25_PARAM_DEFAULTS) == 14
    declared = {name for name in PlanSettings.model_fields if name.startswith("v25_")}
    assert declared == set(V25_FLAG_DEFAULTS) | set(V25_PARAM_DEFAULTS)


def test_u6_flag_defaults_match_the_flag_table():
    settings = get_settings()
    for flag, expected in V25_FLAG_DEFAULTS.items():
        assert getattr(settings, flag) is expected, flag
    on_flags = [flag for flag, value in V25_FLAG_DEFAULTS.items() if value]
    assert on_flags == ["v25_plan_tool_required"]


def test_u6_only_tool_required_is_on_by_default():
    off_flags = [
        flag
        for flag, value in V25_FLAG_DEFAULTS.items()
        if flag != "v25_plan_tool_required"
    ]
    assert len(off_flags) == 12
    assert V25_FLAG_DEFAULTS["v25_plan_tool_required"] is True
    assert all(V25_FLAG_DEFAULTS[flag] is False for flag in off_flags)


def test_u6_param_defaults_match_the_param_table():
    settings = get_settings()
    for name, expected in V25_PARAM_DEFAULTS.items():
        assert getattr(settings, name) == expected, name


def test_u12_every_constrained_param_has_a_negative_case():
    assert len(CONSTRAINED_PARAMS) == 12
    assert len(set(CONSTRAINED_PARAMS)) == 12
    assert set(CONSTRAINED_PARAMS) | set(UNCONSTRAINED_PARAMS) == set(
        V25_PARAM_DEFAULTS
    )


@pytest.mark.parametrize("name", CONSTRAINED_PARAMS)
def test_u12_constraint_has_a_negative_case(name):
    if name in POSITIVE_PARAM_CONSTRAINTS:
        value = 0
    elif name in NON_NEGATIVE_PARAM_CONSTRAINTS:
        value = -1
    else:
        value = 1.5
    with pytest.raises(SettingsError) as excinfo:
        PlanSettings(**{name: value})
    assert name.upper() in str(excinfo.value)


def test_u12_lower_boundary_negatives_are_rejected():
    with pytest.raises(SettingsError):
        PlanSettings(v25_plan_max_steps=-3)
    with pytest.raises(SettingsError):
        PlanSettings(v25_plan_revision_budget=-1)
    with pytest.raises(SettingsError):
        PlanSettings(v25_plan_replan_min_confidence=-0.1)
    with pytest.raises(SettingsError):
        PlanSettings(v25_plan_memory_importance_floor=-0.1)
    with pytest.raises(SettingsError):
        PlanSettings(v25_plan_context_memory_limit=-1)


def test_u12_boundary_values_are_accepted():
    settings = PlanSettings(
        v25_plan_max_steps=1,
        v25_plan_max_depth=1,
        v25_plan_step_max_attempts=1,
        v25_plan_revision_budget=0,
        v25_plan_ttl_hours=1,
        v25_plan_step_cooldown_minutes=0,
        v25_plan_observation_window_minutes=1,
        v25_plan_context_memory_limit=0,
        v25_plan_context_insight_limit=0,
        v25_plan_replan_min_confidence=0.0,
        v25_plan_reflection_min_samples=1,
        v25_plan_memory_importance_floor=1.0,
    )
    assert settings.v25_plan_revision_budget == 0
    assert settings.v25_plan_replan_min_confidence == 0.0
    assert settings.v25_plan_memory_importance_floor == 1.0


def test_i1_plan_settings_is_merged_into_the_global_settings():
    settings = get_settings()
    assert isinstance(settings, PlanSettings)
    assert isinstance(settings, Settings)
    assert "v25_planning_enabled" in Settings.model_fields
    assert "v25_plan_max_steps" in Settings.model_fields
    assert settings.v25_planning_enabled is False
    assert settings.v25_plan_max_steps == 5


def test_i1_the_twenty_seven_v25_fields_are_readable_from_the_global_settings():
    settings = get_settings()
    names = sorted(name for name in dir(settings) if name.startswith("v25_"))
    assert len(names) == 27
    assert set(names) == set(V25_FLAG_DEFAULTS) | set(V25_PARAM_DEFAULTS)


def test_plan_settings_reads_from_the_environment(monkeypatch):
    monkeypatch.setenv("V25_PLANNING_ENABLED", "true")
    monkeypatch.setenv("V25_PLAN_MAX_STEPS", "9")
    monkeypatch.setenv("V25_PLAN_LLM_PROFILE", "planning")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.v25_planning_enabled is True
        assert settings.v25_plan_max_steps == 9
        assert settings.v25_plan_llm_profile == "planning"
    finally:
        get_settings.cache_clear()


def test_plan_settings_declares_no_business_logic_beyond_self_validation():
    methods = sorted(
        name
        for name in vars(PlanSettings)
        if not name.startswith("_") and callable(getattr(PlanSettings, name, None))
    )
    assert methods == ["validate_plan_config"]
    assert PlanSettings.model_config["extra"] == "ignore"
