"""PLAN-002 U6 / U12 / I1：`PlanSettings` 的 2 策略位、14 参数默认值与参数自校验。

默认值逐条写死（Task Detail §4.5.1 / §4.5.2），源码与表的任何差异即失败。

语义反转（v25 去门控）：原 13 个 Flag 中 11 个已随 `vXX_` 开关体系删除，编排恒常开；
`plan_context_digest_enabled` 已于批次 2 固化常开并删除（计划落库恒写 digest），
保留的 `plan_tool_required` 是默认 ON 的策略位，不再是「激活计划编排」的闸门。
本模块按此口径显式更新（范围标记纪律）。
"""

import pytest

from app.core.settings import Settings, get_settings
from app.core.settings._shared import SettingsError
from app.core.settings.plan import PlanSettings

V25_FLAG_DEFAULTS = {
    "plan_tool_required": True,
}

V25_PARAM_DEFAULTS = {
    "plan_max_steps": 5,
    "plan_max_depth": 2,
    "plan_step_max_attempts": 2,
    "plan_revision_budget": 3,
    "plan_ttl_hours": 168,
    "plan_step_cooldown_minutes": 30,
    "plan_observation_window_minutes": 120,
    "plan_context_memory_limit": 5,
    "plan_context_insight_limit": 5,
    "plan_llm_profile": "",
    "plan_replan_min_confidence": 0.7,
    "plan_reflection_min_samples": 3,
    "plan_memory_importance_floor": 0.6,
}

POSITIVE_PARAM_CONSTRAINTS = (
    "plan_max_steps",
    "plan_max_depth",
    "plan_step_max_attempts",
    "plan_ttl_hours",
    "plan_observation_window_minutes",
    "plan_reflection_min_samples",
)

NON_NEGATIVE_PARAM_CONSTRAINTS = (
    "plan_revision_budget",
    "plan_step_cooldown_minutes",
    "plan_context_memory_limit",
    "plan_context_insight_limit",
)

UNIT_INTERVAL_PARAM_CONSTRAINTS = (
    "plan_replan_min_confidence",
    "plan_memory_importance_floor",
)


CONSTRAINED_PARAMS = (
    POSITIVE_PARAM_CONSTRAINTS
    + NON_NEGATIVE_PARAM_CONSTRAINTS
    + UNIT_INTERVAL_PARAM_CONSTRAINTS
)

UNCONSTRAINED_PARAMS = ("plan_llm_profile",)


def test_u6_plan_settings_declares_one_policy_flag_and_thirteen_params():
    assert len(V25_FLAG_DEFAULTS) == 1
    assert len(V25_PARAM_DEFAULTS) == 13
    declared = set(PlanSettings.model_fields)
    assert declared == set(V25_FLAG_DEFAULTS) | set(V25_PARAM_DEFAULTS)


def test_u6_removed_gates_are_absent_from_the_settings():
    removed = (
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
    for name in removed:
        assert name not in PlanSettings.model_fields, name
        assert name not in Settings.model_fields, name


def test_u6_flag_defaults_match_the_flag_table():
    settings = get_settings()
    for flag, expected in V25_FLAG_DEFAULTS.items():
        assert getattr(settings, flag) is expected, flag


def test_u6_policy_flag_defaults_on():
    assert all(V25_FLAG_DEFAULTS.values())
    assert V25_FLAG_DEFAULTS["plan_tool_required"] is True


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
        PlanSettings(plan_max_steps=-3)
    with pytest.raises(SettingsError):
        PlanSettings(plan_revision_budget=-1)
    with pytest.raises(SettingsError):
        PlanSettings(plan_replan_min_confidence=-0.1)
    with pytest.raises(SettingsError):
        PlanSettings(plan_memory_importance_floor=-0.1)
    with pytest.raises(SettingsError):
        PlanSettings(plan_context_memory_limit=-1)


def test_u12_boundary_values_are_accepted():
    settings = PlanSettings(
        plan_max_steps=1,
        plan_max_depth=1,
        plan_step_max_attempts=1,
        plan_revision_budget=0,
        plan_ttl_hours=1,
        plan_step_cooldown_minutes=0,
        plan_observation_window_minutes=1,
        plan_context_memory_limit=0,
        plan_context_insight_limit=0,
        plan_replan_min_confidence=0.0,
        plan_reflection_min_samples=1,
        plan_memory_importance_floor=1.0,
    )
    assert settings.plan_revision_budget == 0
    assert settings.plan_replan_min_confidence == 0.0
    assert settings.plan_memory_importance_floor == 1.0


def test_i1_plan_settings_is_merged_into_the_global_settings():
    settings = get_settings()
    assert isinstance(settings, PlanSettings)
    assert isinstance(settings, Settings)
    assert "plan_tool_required" in Settings.model_fields
    assert "plan_max_steps" in Settings.model_fields
    assert settings.plan_tool_required is True
    assert settings.plan_max_steps == 5


def test_i1_the_fourteen_v25_fields_are_readable_from_the_global_settings():
    settings = get_settings()
    names = sorted(PlanSettings.model_fields)
    assert len(names) == 14
    assert set(names) == set(V25_FLAG_DEFAULTS) | set(V25_PARAM_DEFAULTS)


def test_plan_settings_reads_from_the_environment(monkeypatch):
    monkeypatch.setenv("PLAN_TOOL_REQUIRED", "false")
    monkeypatch.setenv("PLAN_MAX_STEPS", "9")
    monkeypatch.setenv("PLAN_LLM_PROFILE", "planning")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.plan_tool_required is False
        assert settings.plan_max_steps == 9
        assert settings.plan_llm_profile == "planning"
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
