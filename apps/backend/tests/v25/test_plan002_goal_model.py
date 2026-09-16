"""PLAN-002 U4/U5/U7~U11 + I4/I5：`SubGoalSpec` / `GoalPlanRecord` 扩展与判据第四事实源。

本模块是可判定证据的集中处：

- **双向兼容**（Task Detail §4.4.2 Q3）：旧 `sub_goals` JSON → 新模型解析成功且新字段取
  默认值；新代码写出的扩展 JSON → 旧版模型定义（`_LegacySubGoalSpec`）解析成功且未知键
  被 `ignore` 丢弃。
- **落点裁决**（Task Detail §4.4.1 Q2）：4 个新字段是模型字段，**不落 `goal_plans`**；
  重读计划行时它们取默认值（真实读写用例）。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import get_args

import pytest
from pydantic import BaseModel, Field, ValidationError

from app.models import goal as goal_model
from app.models.goal import (
    CRITERION_FACT_SOURCES,
    ON_FAILURE_MODES,
    PLANNING_TRIGGER_VALUES,
    RETRY_MODES,
    STEP_KINDS,
    GoalPlanRecord,
    SubGoalSpec,
    validate_sub_goals,
)
from app.repositories import goal_repository
from app.services import goal_planning
from app.services.planning import goal_contract

from .conftest import V25_NOW

V240_SUB_GOALS_SNAPSHOT = [
    {
        "index": 1,
        "description": "推送一条提醒",
        "capability": "create_reminder",
        "params": {"content": "该休息了"},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    }
]

V240_PLAN_SNAPSHOT = {
    "goal_id": "goal-legacy",
    "version": 1,
    "status": "active",
    "sub_goals": V240_SUB_GOALS_SNAPSHOT,
    "rejection_reason": None,
    "created_at": "2026-09-08T12:00:00",
    "updated_at": "2026-09-08T12:00:00",
}

PLAN_002_SUB_GOAL_FIELDS = (
    "tool_id",
    "kind",
    "retry_policy",
    "on_failure",
    "expected_effects",
    "observation_keys",
    "binding_reason",
)

PLAN_002_GOAL_PLAN_FIELDS = (
    "trigger",
    "context_digest",
    "revision_of",
    "evidence_refs",
)

V240_SUB_GOAL_SPEC_FIELDS = (
    "index",
    "description",
    "capability",
    "params",
    "criteria",
    "depends_on",
    "parent_index",
    "status",
    "attempt_count",
    "last_observed_at",
    "last_attempt_at",
    "failure_note",
)


class _LegacySubGoalSpec(BaseModel):
    """V2.4.0 的 `SubGoalSpec` 定义冻结副本（旧读取方），用于「新 → 旧」兼容断言。"""

    index: int = Field(ge=1)
    description: str = Field(max_length=40)
    capability: str = Field(min_length=1)
    params: dict = Field(default_factory=dict)
    criteria: dict
    depends_on: list[int] = Field(default_factory=list)
    parent_index: int | None = Field(default=None, ge=1)
    status: str = "pending"
    attempt_count: int = 0
    last_observed_at: datetime | None = None
    last_attempt_at: datetime | None = None
    failure_note: str | None = None


def _extended_spec(**overrides) -> SubGoalSpec:
    payload = {
        "index": 1,
        "description": "推送一条提醒",
        "capability": "create_reminder",
        "params": {"content": "该休息了"},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
        "tool_id": "builtin.reminder.create",
        "kind": "tool",
        "retry_policy": "until_budget",
        "on_failure": "replan",
        "expected_effects": ("note", "external"),
        "observation_keys": ("reminder_id",),
        "binding_reason": "tool_selector",
    }
    payload.update(overrides)
    return SubGoalSpec.model_validate(payload)


def test_u4_expected_effects_outside_tool_effect_kinds_are_rejected(make_spec):
    assert SubGoalSpec.model_validate(
        make_spec(expected_effects=("world", "memory", "relationship", "note", "external"))
    ).expected_effects == ("world", "memory", "relationship", "note", "external")
    with pytest.raises(ValidationError) as excinfo:
        SubGoalSpec.model_validate(make_spec(expected_effects=("world", "money")))
    assert "expected_effects" in str(excinfo.value)
    assert "TOOL_EFFECT_KINDS" in str(excinfo.value)
    with pytest.raises(ValidationError):
        SubGoalSpec.model_validate(make_spec(expected_effects=["nope"]))


def test_u4_expected_effects_defaults_to_empty_and_writes_through_json():
    spec = SubGoalSpec.model_validate(V240_SUB_GOALS_SNAPSHOT[0])
    assert spec.expected_effects == ()
    extended = _extended_spec()
    assert extended.model_dump(mode="json")["expected_effects"] == ["note", "external"]
    assert (
        SubGoalSpec.model_validate(extended.model_dump(mode="json")).expected_effects
        == ("note", "external")
    )


def test_u5_plan_trigger_outside_the_three_triggers_is_rejected():
    GoalPlanRecord(
        goal_id="goal-1",
        version=1,
        trigger="goal_replan",
        created_at=V25_NOW,
        updated_at=V25_NOW,
    )
    with pytest.raises(ValidationError) as excinfo:
        GoalPlanRecord(
            goal_id="goal-1",
            version=1,
            trigger="goal_whatever",
            created_at=V25_NOW,
            updated_at=V25_NOW,
        )
    assert "goal_whatever" in str(excinfo.value)


def test_u5_trigger_value_set_matches_the_existing_three_constants():
    assert goal_model.PLANNING_TRIGGER_VALUES == (
        "goal_created",
        "goal_blocked",
        "goal_replan",
    )
    assert (
        get_args(goal_model.PlanningTrigger) == goal_model.PLANNING_TRIGGER_VALUES
    )
    assert goal_model.PLANNING_TRIGGER_VALUES == goal_planning.PLANNING_TRIGGERS
    assert goal_model.PLANNING_TRIGGER_VALUES == goal_contract.PLANNING_TRIGGER_VALUES


def test_step_kind_retry_on_failure_value_sets_are_frozen():
    assert STEP_KINDS == ("tool", "observe", "composite")
    assert RETRY_MODES == ("none", "once", "until_budget")
    assert ON_FAILURE_MODES == ("abort", "skip", "replan", "continue")
    assert get_args(goal_model.StepKind) == STEP_KINDS
    assert get_args(goal_model.RetryMode) == RETRY_MODES
    assert get_args(goal_model.OnFailureMode) == ON_FAILURE_MODES


def test_sub_goal_enum_fields_are_literals_with_safe_defaults():
    spec = SubGoalSpec.model_validate(V240_SUB_GOALS_SNAPSHOT[0])
    assert (spec.tool_id, spec.kind, spec.retry_policy, spec.on_failure) == (
        None,
        "tool",
        "once",
        "skip",
    )
    assert spec.binding_reason is None
    assert SubGoalSpec.model_fields["on_failure"].default == "skip"
    assert SubGoalSpec.model_fields["kind"].default == "tool"
    assert SubGoalSpec.model_fields["retry_policy"].default == "once"
    assert SubGoalSpec.model_fields["tool_id"].default is None
    assert SubGoalSpec.model_fields["binding_reason"].default is None
    assert SubGoalSpec.model_fields["expected_effects"].default == ()
    assert SubGoalSpec.model_fields["observation_keys"].default == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "x"),
        ("retry_policy", "x"),
        ("on_failure", "x"),
    ],
)
def test_u2_sub_goal_enum_fields_reject_illegal_values(make_spec, field, value):
    with pytest.raises(ValidationError):
        SubGoalSpec.model_validate(make_spec(**{field: value}))


def test_u7_old_sub_goals_json_parses_with_default_new_fields():
    specs = validate_sub_goals([dict(V240_SUB_GOALS_SNAPSHOT[0])])
    assert len(specs) == 1
    spec = specs[0]
    assert tuple(SubGoalSpec.model_fields)[:12] == V240_SUB_GOAL_SPEC_FIELDS
    for field in PLAN_002_SUB_GOAL_FIELDS:
        assert field in SubGoalSpec.model_fields, field
    assert (spec.kind, spec.retry_policy, spec.on_failure) == ("tool", "once", "skip")
    assert spec.expected_effects == ()
    assert spec.observation_keys == ()
    assert (spec.tool_id, spec.binding_reason) == (None, None)


def test_u7_old_goal_plan_snapshot_parses_with_default_new_fields():
    legacy = goal_model.GoalPlanRecord.model_validate(V240_PLAN_SNAPSHOT)
    assert tuple(GoalPlanRecord.model_fields)[:8] == (
        "id",
        "goal_id",
        "version",
        "status",
        "sub_goals",
        "rejection_reason",
        "created_at",
        "updated_at",
    )
    for field in PLAN_002_GOAL_PLAN_FIELDS:
        assert field in GoalPlanRecord.model_fields, field
    assert legacy.trigger == "goal_created"
    assert legacy.context_digest is None
    assert legacy.revision_of is None
    assert legacy.evidence_refs == ()
    assert legacy.sub_goals[0].kind == "tool"


def test_u7_new_fields_are_declared_in_the_model_source_not_only_in_json():
    source = Path(goal_model.__file__).read_text(encoding="utf-8")
    for field in PLAN_002_SUB_GOAL_FIELDS + PLAN_002_GOAL_PLAN_FIELDS:
        assert f"    {field}:" in source, field


def test_u7_extra_policy_is_still_the_pydantic_default_ignore():
    assert SubGoalSpec.model_config.get("extra") is None
    assert GoalPlanRecord.model_config.get("extra") is None
    payload = dict(V240_SUB_GOALS_SNAPSHOT[0], unknown_key="ignored")
    assert SubGoalSpec.model_validate(payload).index == 1


def test_u8_new_payload_is_readable_by_the_legacy_model_definition():
    extended = _extended_spec()
    payload = extended.model_dump(mode="json")
    assert set(payload) - set(V240_SUB_GOAL_SPEC_FIELDS) == set(
        PLAN_002_SUB_GOAL_FIELDS
    )
    legacy = _LegacySubGoalSpec.model_validate(json.loads(json.dumps(payload)))
    assert legacy.index == 1
    assert legacy.capability == "create_reminder"
    assert "tool_id" not in _LegacySubGoalSpec.model_fields
    assert "on_failure" not in _LegacySubGoalSpec.model_fields


def test_u8_round_trip_through_the_extended_model_preserves_extensions():
    extended = _extended_spec()
    stored = json.loads(json.dumps(extended.model_dump(mode="json")))
    restored = SubGoalSpec.model_validate(stored)
    assert restored == extended
    assert restored.binding_reason == "tool_selector"
    assert restored.observation_keys == ("reminder_id",)


def test_u9_criterion_fact_sources_is_four_values_in_declared_order():
    assert CRITERION_FACT_SOURCES == ("world", "state", "memory", "tool")
    assert len(CRITERION_FACT_SOURCES) == 4
    assert len(set(CRITERION_FACT_SOURCES)) == 4
    assert goal_model.CRITERION_TOOL_FACT_SOURCE == "tool"


def test_u9_other_criterion_value_sets_are_untouched():
    assert goal_model.CRITERION_TYPES == (
        "action_succeeded",
        "field_equals",
        "threshold_reached",
        "all_of",
        "any_of",
    )
    assert goal_model.CRITERION_METRIC_PATHS == (
        "tension",
        "intimacy",
        "mood",
        "salient_memory_count",
    )
    assert goal_model.CRITERION_OPS == (">=", "<=")
    assert goal_model.COMPOSITE_CRITERION_TYPES == ("all_of", "any_of")


def test_u10_tool_fact_source_rejects_threshold_reached():
    with pytest.raises(ValueError) as excinfo:
        SubGoalSpec.validate_criteria(
            {
                "type": "threshold_reached",
                "source": "tool",
                "path": "tension",
                "op": ">=",
                "value": 0.5,
            }
        )
    message = str(excinfo.value)
    assert "threshold_reached" in message
    assert "tool" in message
    assert "不支持" in message


def test_u10_tool_fact_source_supports_field_equals():
    SubGoalSpec.validate_criteria(
        {
            "type": "field_equals",
            "source": "tool",
            "path": "reminder_id",
            "value": "rem-1",
        }
    )


def test_u10_tool_fact_source_rejection_is_not_bypassed_by_composites():
    with pytest.raises(ValueError):
        SubGoalSpec.validate_criteria(
            {
                "type": "all_of",
                "children": [
                    {
                        "type": "threshold_reached",
                        "source": "tool",
                        "path": "mood",
                        "op": ">=",
                        "value": 1,
                    }
                ],
            }
        )


def test_u10_observation_key_whitelist_is_enforced_by_plan_005_not_by_validate_criteria():
    SubGoalSpec.validate_criteria(
        {
            "type": "field_equals",
            "source": "tool",
            "path": "undeclared_key",
            "value": 1,
        }
    )


@pytest.mark.parametrize(
    "criteria",
    [
        {"type": "action_succeeded", "capability": "create_reminder"},
        {"type": "action_succeeded", "capability": "create_reminder", "within_minutes": 5},
        {"type": "field_equals", "source": "world", "path": "weather", "value": "rain"},
        {"type": "field_equals", "source": "state", "path": "mood", "value": 0.5},
        {"type": "field_equals", "source": "memory", "path": "count", "value": 2},
        {
            "type": "threshold_reached",
            "source": "state",
            "path": "tension",
            "op": ">=",
            "value": 0.5,
        },
        {
            "type": "threshold_reached",
            "source": "world",
            "path": "intimacy",
            "op": "<=",
            "value": 0.5,
        },
        {
            "type": "threshold_reached",
            "source": "memory",
            "path": "salient_memory_count",
            "op": ">=",
            "value": 1,
        },
        {
            "type": "all_of",
            "children": [{"type": "action_succeeded", "capability": "create_reminder"}],
        },
        {
            "type": "any_of",
            "children": [{"type": "action_succeeded", "capability": "create_reminder"}],
        },
    ],
)
def test_u11_the_three_legacy_fact_sources_keep_their_behaviour(criteria):
    assert SubGoalSpec.validate_criteria(criteria) is None


@pytest.mark.parametrize(
    "criteria",
    [
        {"type": "unknown"},
        {"type": "action_succeeded"},
        {"type": "action_succeeded", "capability": "c", "within_minutes": 0},
        {"type": "field_equals", "source": "unknown", "path": "p", "value": 1},
        {"type": "field_equals", "source": "world", "value": 1},
        {"type": "field_equals", "source": "world", "path": "p"},
        {
            "type": "threshold_reached",
            "source": "unknown",
            "path": "tension",
            "op": ">=",
            "value": 1,
        },
        {
            "type": "threshold_reached",
            "source": "state",
            "path": "unknown",
            "op": ">=",
            "value": 1,
        },
        {
            "type": "threshold_reached",
            "source": "state",
            "path": "tension",
            "op": "==",
            "value": 1,
        },
        {
            "type": "threshold_reached",
            "source": "state",
            "path": "tension",
            "op": ">=",
            "value": "high",
        },
        {"type": "all_of", "children": []},
        {
            "type": "all_of",
            "children": [
                {
                    "type": "all_of",
                    "children": [{"type": "action_succeeded", "capability": "c"}],
                }
            ],
        },
    ],
)
def test_u11_legacy_rejections_are_unchanged(criteria):
    with pytest.raises(ValueError):
        SubGoalSpec.validate_criteria(criteria)


def test_u11_legacy_rejection_messages_are_unchanged():
    with pytest.raises(ValueError) as excinfo:
        SubGoalSpec.validate_criteria({"type": "threshold_reached", "source": "state"})
    assert "指标路径不在白名单" in str(excinfo.value)
    with pytest.raises(ValueError) as excinfo:
        SubGoalSpec.validate_criteria({"type": "field_equals", "source": "nope"})
    assert "事实源不在白名单" in str(excinfo.value)


def test_i4_update_plan_progress_round_trips_the_extended_fields(make_goal, make_plan):
    goal = make_goal(description="扩展字段读写目标")
    plan = make_plan(goal.id)
    specs = [_extended_spec()]
    updated = goal_repository.update_plan_progress(plan.id, specs)
    assert updated is not None
    stored = goal_repository.get_plan(plan.id).sub_goals[0]
    assert stored.tool_id == "builtin.reminder.create"
    assert stored.kind == "tool"
    assert stored.on_failure == "replan"
    assert stored.expected_effects == ("note", "external")
    assert stored.observation_keys == ("reminder_id",)
    assert stored.binding_reason == "tool_selector"
    assert goal_repository.get_goal(goal.id).status == "active"


def test_i4_legacy_sub_goals_payload_survives_a_progress_write(make_goal, make_plan):
    goal = make_goal(description="旧载荷读写目标")
    plan = make_plan(goal.id)
    legacy = validate_sub_goals([dict(V240_SUB_GOALS_SNAPSHOT[0])])
    assert goal_repository.update_plan_progress(plan.id, legacy) is not None
    stored = goal_repository.get_plan(plan.id).sub_goals[0]
    assert stored.status == "pending"
    assert stored.kind == "tool"
    assert stored.tool_id is None


def test_i5_plan_record_extensions_are_not_persisted_into_goal_plans(make_goal):
    goal = make_goal(description="落点裁决目标")
    record = goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal.id,
            version=1,
            status="active",
            trigger="goal_replan",
            context_digest="digest-abc",
            revision_of=None,
            evidence_refs=("insight-1",),
            created_at=V25_NOW,
            updated_at=V25_NOW,
        )
    )
    reloaded = goal_repository.get_plan(record.id)
    assert reloaded.goal_id == goal.id
    assert reloaded.version == 1
    assert reloaded.trigger == "goal_created"
    assert reloaded.context_digest is None
    assert reloaded.revision_of is None
    assert reloaded.evidence_refs == ()
    assert goal_repository.get_latest_plan(goal.id).id == record.id


def test_i5_plan_face_reads_are_unaffected_by_the_extension(make_goal, make_plan):
    goal = make_goal(description="计划面读面目标")
    make_plan(goal.id, version=1)
    make_plan(goal.id, version=2)
    plans = goal_repository.list_plans(goal.id)
    assert [plan.version for plan in plans] == [2, 1]
    assert goal_repository.count_plans(goal.id) == 2
    assert goal_repository.get_latest_plan(goal.id).version == 2
