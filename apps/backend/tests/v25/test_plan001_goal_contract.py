"""PLAN-001 U 系列：Goal 域契约快照（Task Detail §8 Step 2 / §9.1 U1~U7）。

口径：快照为**字面量冻结**——每个断言把期望值写死在用例里（而非从被测模块反推），
被测源码与快照的任何差异都会让用例失败。这正是「差异必须为空」的可判定形式。

PLAN-002 交接留痕：`CRITERION_FACT_SOURCES` 的快照由 PLAN-002 从三值扩为四值
（新增 `"tool"`，`fact_source="tool"` 下 `threshold_reached` 被拒），本模块随之更新该
字面量与对应边界用例；其余值集与表结构快照仍由 PLAN-001 冻结，本任务零改动。
"""

import importlib
import inspect
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from app.core.db import GoalPlanRow, GoalRow
from app.models import goal as goal_model
from app.models.observability import DecisionKind
from app.models.goal import (
    COMPOSITE_CRITERION_TYPES,
    CRITERION_FACT_SOURCES,
    CRITERION_METRIC_PATHS,
    CRITERION_OPS,
    CRITERION_TYPES,
    GOAL_DESCRIPTION_MAX_LENGTH,
    GOAL_PRIORITY_MAX,
    GOAL_PRIORITY_MIN,
    GOAL_TRANSITIONS,
    V1_STATUS_TARGETS,
    IllegalGoalTransition,
    SubGoalSpec,
    goal_transitions,
)
from app.repositories import goal_repository
from app.services import goal_observation, goal_planning
from app.services.planning import goal_contract

VALUE_SET_SNAPSHOT = {
    "GoalType": ("user_care", "relationship", "conversation", "scene"),
    "GoalStatus": (
        "active",
        "completed",
        "expired",
        "cancelled",
        "failed",
        "suspended",
        "abandoned",
    ),
    "GoalSource": ("definition", "policy", "scene"),
    "GoalHorizon": ("persistent", "current"),
    "GoalLayer": ("short_term", "medium", "long_term"),
    "GoalDomain": ("personal", "relationship", "world"),
    "GoalPlanStatus": ("draft", "validated", "active", "rejected", "superseded"),
    "SubGoalStatus": ("pending", "in_progress", "done", "failed"),
}

TUPLE_SNAPSHOT = {
    "LAYER_VALUES": ("short_term", "medium", "long_term"),
    "DOMAIN_VALUES": ("personal", "relationship", "world"),
    "PLAN_STATUS_VALUES": ("draft", "validated", "active", "rejected", "superseded"),
    "SUB_GOAL_STATUS_VALUES": ("pending", "in_progress", "done", "failed"),
    "V1_STATUS_TARGETS": ("completed", "expired", "cancelled"),
    "GOAL_ORIGINS": (
        "insight",
        "commitment",
        "user",
        "world",
        "evolution",
        "development_modulation",
        "relationship_pattern",
        "salient_memory",
        "world_event",
    ),
    "CRITERION_TYPES": (
        "action_succeeded",
        "field_equals",
        "threshold_reached",
        "all_of",
        "any_of",
    ),
    "CRITERION_FACT_SOURCES": ("world", "state", "memory", "tool"),
    "CRITERION_METRIC_PATHS": (
        "tension",
        "intimacy",
        "mood",
        "salient_memory_count",
    ),
    "CRITERION_OPS": (">=", "<="),
    "COMPOSITE_CRITERION_TYPES": ("all_of", "any_of"),
}

DICT_SNAPSHOT = {
    "LAYER_DEPTH": {"long_term": 3, "medium": 2, "short_term": 1},
    "GOAL_TIER": {"scene": 0, "user_care": 1, "relationship": 2, "conversation": 3},
}

GOAL_TRANSITIONS_SNAPSHOT = {
    "active": ("completed", "failed", "abandoned", "suspended"),
    "suspended": ("active", "abandoned"),
    "failed": ("active",),
    "completed": (),
    "abandoned": (),
    "expired": (),
    "cancelled": (),
}

TERMINAL_STATUSES = ("completed", "abandoned", "expired", "cancelled")

PLANNING_REASON_WHITELIST_SNAPSHOT = {
    "goal_planning": {
        "REASON_ATTEMPT_CAP": "attempt_cap",
        "REASON_COUNT_EXCEEDED": "subgoal_count_exceeded",
        "REASON_CAPABILITY_UNALIGNED": "capability_unaligned",
        "REASON_INVALID_SHAPE": "invalid_sub_goal_shape",
        "REASON_LLM_FAILED": "llm_failed",
    },
    "goal_observation": {
        "REASON_COMPLETED": "goal_completed",
        "REASON_PERIOD_EXCEEDED": "exec_period_exceeded",
        "REASON_THRESHOLD_EXCEEDED": "subgoal_threshold_exceeded",
        "REASON_REPLAN_EXHAUSTED": "replan_exhausted",
    },
}

GOAL_REPOSITORY_PLAN_FACE_SIGNATURES = {
    "create_plan": "(record: app.models.goal.GoalPlanRecord) -> app.models.goal.GoalPlanRecord",
    "get_plan": "(plan_id: str) -> app.models.goal.GoalPlanRecord | None",
    "list_plans": "(goal_id: str) -> list[app.models.goal.GoalPlanRecord]",
    "get_latest_plan": "(goal_id: str) -> app.models.goal.GoalPlanRecord | None",
    "count_plans": "(goal_id: str) -> int",
    "set_plan_status": "(plan_id: str, status: str) -> app.models.goal.GoalPlanRecord | None",
    "set_plan_rejection": "(plan_id: str, reason: str) -> app.models.goal.GoalPlanRecord | None",
    "update_plan_progress": (
        "(plan_id: str, sub_goals: list[app.models.goal.SubGoalSpec])"
        " -> app.models.goal.GoalPlanRecord | None"
    ),
    "list_active_plans": (
        "(user_id: str) -> list[tuple[app.models.goal.GoalRecord,"
        " app.models.goal.GoalPlanRecord]]"
    ),
}

GOAL_REPOSITORY_STATE_FACE_SIGNATURES = {
    "set_status": (
        "(goal_id: str, target: str, arbitration_state: dict | None = None)"
        " -> app.models.goal.GoalRecord | None"
    ),
    "finish_goal": (
        "(goal_id: str, status: str, failure_reason: str | None = None)"
        " -> app.models.goal.GoalRecord | None"
    ),
    "complete_goal": "(goal_id: str) -> app.models.goal.GoalRecord | None",
    "fail_goal": "(goal_id: str, failure_reason: str) -> app.models.goal.GoalRecord | None",
    "reactivate_goal": "(goal_id: str) -> app.models.goal.GoalRecord | None",
}

GOAL_COLUMNS_SNAPSHOT = (
    "arbitration_state",
    "character_id",
    "created_at",
    "created_turn",
    "description",
    "domain",
    "expires_at_turn",
    "failure_reason",
    "horizon",
    "id",
    "layer",
    "origin",
    "parent_goal_id",
    "priority",
    "source",
    "status",
    "type",
    "updated_at",
    "user_id",
)

GOAL_PLAN_COLUMNS_SNAPSHOT = (
    "created_at",
    "goal_id",
    "id",
    "rejection_reason",
    "status",
    "sub_goals",
    "updated_at",
    "version",
)

GOAL_CHECK_NAMES_SNAPSHOT = (
    "ck_character_goals_domain",
    "ck_character_goals_horizon",
    "ck_character_goals_layer",
    "ck_character_goals_priority",
    "ck_character_goals_source",
    "ck_character_goals_status",
    "ck_character_goals_type",
)

GOAL_PLAN_CHECK_NAMES_SNAPSHOT = ("ck_goal_plans_status",)

GOAL_INDEX_NAMES_SNAPSHOT = (
    "idx_character_goals_layer_domain",
    "idx_character_goals_parent",
    "idx_character_goals_user_status",
)

GOAL_PLAN_INDEX_NAMES_SNAPSHOT = ("idx_goal_plans_goal_status",)

DECISION_KIND_SNAPSHOT = (
    "proactive_autonomy",
    "turn_goal",
    "turn_intention",
    "turn_behavior",
    "goal_lifecycle",
)

NON_PLANNING_WRITE_FACE = (
    "expire_goal",
    "cancel_goal",
    "create_goal",
    "create_hierarchical_goal",
    "seed_goals",
)

MIGRATION_HEAD = "0052"


def _check_names(table) -> tuple[str, ...]:
    return tuple(
        sorted(
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )
    )


def _index_names(table) -> tuple[str, ...]:
    return tuple(sorted(index.name for index in table.indexes))


def _signature(name: str) -> str:
    return str(inspect.signature(getattr(goal_repository, name)))


def test_u1_eight_value_sets_are_frozen():
    for name, expected in VALUE_SET_SNAPSHOT.items():
        assert get_args(getattr(goal_model, name)) == expected, name


def test_u1_tuple_and_dict_constants_are_frozen():
    for name, expected in TUPLE_SNAPSHOT.items():
        assert getattr(goal_model, name) == expected, name
    for name, expected in DICT_SNAPSHOT.items():
        assert getattr(goal_model, name) == expected, name
    assert GOAL_DESCRIPTION_MAX_LENGTH == 40
    assert (GOAL_PRIORITY_MIN, GOAL_PRIORITY_MAX) == (1, 5)


def test_u2_transition_table_matches_state_machine_diagram():
    assert GOAL_TRANSITIONS == GOAL_TRANSITIONS_SNAPSHOT


def test_u2_transition_table_covers_all_statuses_with_closed_terminal_states():
    statuses = set(VALUE_SET_SNAPSHOT["GoalStatus"])
    assert set(GOAL_TRANSITIONS) == statuses
    for status in TERMINAL_STATUSES:
        assert not GOAL_TRANSITIONS[status], status
    for source, targets in GOAL_TRANSITIONS.items():
        assert set(targets) <= statuses, source


def test_u2_failed_and_suspended_hold_the_only_edges_back_to_active():
    assert GOAL_TRANSITIONS["failed"] == ("active",)
    assert GOAL_TRANSITIONS["suspended"] == ("active", "abandoned")
    sources_with_active_target = {
        status for status, targets in GOAL_TRANSITIONS.items() if "active" in targets
    }
    assert sources_with_active_target == {"failed", "suspended"}


def test_u3_layered_and_v1_branches_are_distinct():
    assert goal_transitions(None, "active") == V1_STATUS_TARGETS
    assert not goal_transitions(None, "completed")
    assert not goal_transitions(None, "suspended")
    for status, targets in GOAL_TRANSITIONS.items():
        assert goal_transitions("long_term", status) == targets, status
    assert not goal_transitions("short_term", "unknown")


def test_u4_terminal_and_backward_edges_have_no_legal_target():
    for layer in ("short_term", "medium", "long_term", None):
        for status in TERMINAL_STATUSES:
            assert not goal_transitions(layer, status), (layer, status)
    assert "active" not in goal_transitions("long_term", "active")
    assert "completed" not in goal_transitions("long_term", "completed")


def test_u4_illegal_transition_error_is_a_value_error():
    assert issubclass(IllegalGoalTransition, ValueError)


def test_u5_criterion_whitelist_is_frozen_at_five_four_four_two():
    assert len(CRITERION_TYPES) == 5
    assert len(CRITERION_FACT_SOURCES) == 4
    assert len(CRITERION_METRIC_PATHS) == 4
    assert len(CRITERION_OPS) == 2
    assert COMPOSITE_CRITERION_TYPES == ("all_of", "any_of")


def test_u5_tool_fact_source_boundary_is_the_plan_002_freeze():
    """第四事实源由 PLAN-002 引入：`field_equals` 放行、`threshold_reached` 拒绝。"""
    SubGoalSpec.validate_criteria(
        {"type": "field_equals", "source": "tool", "path": "reminder_id", "value": "rem-1"}
    )
    with pytest.raises(ValueError):
        SubGoalSpec.validate_criteria(
            {
                "type": "threshold_reached",
                "source": "tool",
                "path": "tension",
                "op": ">=",
                "value": 0.5,
            }
        )


def test_u5_composite_criteria_allow_exactly_one_nesting_level():
    SubGoalSpec.validate_criteria(
        {
            "type": "all_of",
            "children": [{"type": "action_succeeded", "capability": "create_reminder"}],
        }
    )
    with pytest.raises(ValueError):
        SubGoalSpec.validate_criteria(
            {
                "type": "all_of",
                "children": [
                    {
                        "type": "any_of",
                        "children": [
                            {"type": "action_succeeded", "capability": "create_reminder"}
                        ],
                    }
                ],
            }
        )


def test_u6_planning_failure_reason_vocabulary_has_exactly_two_terms():
    assert goal_contract.PLANNING_FAILURE_REASONS == (
        "plan_exhausted",
        "criteria_undecidable",
    )
    assert goal_contract.PLANNING_FAILURE_REASON_PLAN_EXHAUSTED == "plan_exhausted"
    assert (
        goal_contract.PLANNING_FAILURE_REASON_CRITERIA_UNDECIDABLE
        == "criteria_undecidable"
    )


def test_u6_failure_reason_column_carries_no_check_constraint():
    column = GoalRow.__table__.c.failure_reason
    assert column.nullable is True
    assert column.type.python_type is str
    offenders = [
        constraint.sqltext.text
        for constraint in GoalRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
        and "failure_reason" in str(constraint.sqltext)
    ]
    assert offenders == []


def test_u7_planning_triggers_are_exactly_three_and_match_declaration():
    assert goal_planning.PLANNING_TRIGGERS == (
        goal_planning.TRIGGER_CREATED,
        goal_planning.TRIGGER_BLOCKED,
        goal_planning.TRIGGER_REPLAN,
    )
    assert goal_planning.TRIGGER_CREATED == "goal_created"
    assert goal_planning.TRIGGER_BLOCKED == "goal_blocked"
    assert goal_planning.TRIGGER_REPLAN == "goal_replan"
    assert goal_planning.PLANNING_TRIGGERS == goal_contract.PLANNING_TRIGGER_VALUES


def test_declared_intervention_points_are_exactly_three_and_use_existing_triggers():
    points = goal_contract.LIFECYCLE_INTERVENTION_POINTS
    assert len(points) == 3
    names = tuple(point[0] for point in points)
    triggers = tuple(point[2] for point in points)
    assert names == ("goal_created", "step_blocked", "plan_revision_approved")
    assert triggers == goal_planning.PLANNING_TRIGGERS
    assert len(set(names)) == 3
    practices = goal_contract.PLANNING_FORBIDDEN_PRACTICES
    assert len(practices) == 8
    assert len(set(practices)) == 8
    assert [name for name in practices if name != name.lower()] == []
    assert practices[-1] == "fourth_lifecycle_intervention_point"
    assert "second_priority_algorithm" in practices
    assert "direct_goal_row_persistence" in practices


def test_declared_read_and_write_interfaces_resolve_to_real_callables():
    for module_path, attribute in goal_contract.PLANNING_READ_INTERFACES:
        assert callable(getattr(importlib.import_module(module_path), attribute))
    for module_path, attribute in goal_contract.PLANNING_WRITE_INTERFACES:
        assert callable(getattr(importlib.import_module(module_path), attribute))
    for module_path, attribute in (
        goal_contract.PLANNING_ATTRIBUTION_TARGET,
        goal_contract.PLANNING_TRIGGER_TARGET,
        goal_contract.PLANNING_ADVANCE_CANDIDATE_GATE,
    ):
        assert callable(getattr(importlib.import_module(module_path), attribute))


def test_write_face_is_exactly_five_functions_and_excludes_other_goal_mutations():
    declared = goal_contract.PLANNING_WRITE_FUNCTION_NAMES
    assert declared == (
        "set_status",
        "finish_goal",
        "complete_goal",
        "fail_goal",
        "reactivate_goal",
    )
    assert tuple(attribute for _, attribute in goal_contract.PLANNING_WRITE_INTERFACES) == (
        declared
    )
    for name in NON_PLANNING_WRITE_FACE:
        assert name not in declared


PLAN_FACE_WRITE_CALLS = (
    "create_plan",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
)
"""PLAN-003 契约演进：计划面四函数进入 `goal_repository` 调用白名单。

口径由「§6.1 ∪ §6.2（12 项）」扩为「§6.1 ∪ §6.2 ∪ 计划面四函数（16 项）」——这是 PLAN-001
已预告的越界评审点（Task Detail §10.3），演进留痕见 `goal_contract` 模块文档 §9。
`PLANNING_WRITE_INTERFACES`（Goal 状态写面恰好 5 个）不受影响：计划面四函数不是 Goal
状态写面，计划被拒仍不改 `GoalStatus`。
"""

PLAN_011_READ_EXTENSIONS = (
    "list_plans_by_status",
    "count_plan_versions",
    "list_terminal_plans_since",
)
"""PLAN-011 契约演进：三个**只读**扩展进入 `goal_repository` 调用白名单。

口径由「§6.1 ∪ §6.2 ∪ 计划面四函数（16 项）」扩为 19 项（Task Detail §6.1 冻结的计划读契约）。
三者与 `PLANNING_READ_INTERFACES`（Goal 域只读消费面）分属两段：前者是计划面读出口，
后者是 Goal 域读面，故本文件按「计划面写面 + PLAN-011 只读扩展」两段并集判定。
演进留痕见 `goal_contract` 模块文档 §10 与 `tests/v25/test_plan011_regression.py`。
"""


def test_declared_goal_repository_whitelist_is_read_face_plus_write_face():
    goal_repository_calls = {
        attribute
        for module_path, attribute in (
            *goal_contract.PLANNING_READ_INTERFACES,
            *goal_contract.PLANNING_WRITE_INTERFACES,
        )
        if module_path == "app.repositories.goal_repository"
    }
    allowed = set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS)
    assert goal_repository_calls <= allowed
    assert allowed - goal_repository_calls == set(PLAN_FACE_WRITE_CALLS) | set(
        PLAN_011_READ_EXTENSIONS
    )
    assert len(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS) == 19


def test_goal_repository_plan_face_signatures_are_frozen():
    for name, expected in GOAL_REPOSITORY_PLAN_FACE_SIGNATURES.items():
        assert _signature(name) == expected, name


def test_goal_repository_state_write_face_signatures_are_frozen():
    for name, expected in GOAL_REPOSITORY_STATE_FACE_SIGNATURES.items():
        assert _signature(name) == expected, name
    assert "arbitration_state" in _signature("set_status")
    assert "arbitration_state" not in _signature("finish_goal")


def test_character_goals_table_shape_is_frozen():
    assert tuple(sorted(GoalRow.__table__.c.keys())) == GOAL_COLUMNS_SNAPSHOT
    assert _check_names(GoalRow.__table__) == GOAL_CHECK_NAMES_SNAPSHOT
    assert _index_names(GoalRow.__table__) == GOAL_INDEX_NAMES_SNAPSHOT
    status_check = next(
        constraint
        for constraint in GoalRow.__table__.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_character_goals_status"
    )
    for status in VALUE_SET_SNAPSHOT["GoalStatus"]:
        assert f"'{status}'" in str(status_check.sqltext)


def test_goal_plans_table_shape_is_frozen():
    assert tuple(sorted(GoalPlanRow.__table__.c.keys())) == GOAL_PLAN_COLUMNS_SNAPSHOT
    assert _check_names(GoalPlanRow.__table__) == GOAL_PLAN_CHECK_NAMES_SNAPSHOT
    assert _index_names(GoalPlanRow.__table__) == GOAL_PLAN_INDEX_NAMES_SNAPSHOT
    unique_names = {
        constraint.name for constraint in GoalPlanRow.__table__.constraints
    }
    assert "uq_goal_plans_goal_version" in unique_names


def test_decision_kind_stays_at_five_values_with_goal_lifecycle_reused():
    assert tuple(kind.value for kind in DecisionKind) == DECISION_KIND_SNAPSHOT


def test_existing_planning_and_observation_reason_codes_are_frozen():
    modules = {
        "goal_planning": goal_planning,
        "goal_observation": goal_observation,
    }
    for module_name, expected in PLANNING_REASON_WHITELIST_SNAPSHOT.items():
        module = modules[module_name]
        for attribute, value in expected.items():
            assert getattr(module, attribute) == value, (module_name, attribute)


def test_migration_chain_head_is_still_0052():
    versions_dir = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
    numbered = sorted(
        int(match.group(1))
        for path in versions_dir.glob("*.py")
        if (match := re.match(r"(\d+)_", path.name))
    )
    assert numbered, "未找到迁移文件"
    assert f"{max(numbered):04d}" == MIGRATION_HEAD


def test_planning_package_declares_the_full_contract_surface():
    assert goal_contract.__doc__
    assert goal_contract.PLANNING_READ_INTERFACES
    assert goal_contract.PLANNING_FORBIDDEN_PRACTICES
    assert len(set(goal_contract.PLANNING_FORBIDDEN_PRACTICES)) == len(
        goal_contract.PLANNING_FORBIDDEN_PRACTICES
    )
    assert goal_contract.GOAL_STATUS_PLANNABLE == ("active",)
    assert set(goal_contract.GOAL_STATUS_TERMINAL) == {
        "completed",
        "failed",
        "abandoned",
        "expired",
        "cancelled",
    }
    assert set(goal_contract.GOAL_STATUS_TERMINAL).isdisjoint(
        goal_contract.GOAL_STATUS_PLANNABLE
    )


def test_goal_record_fields_are_frozen():
    assert tuple(goal_model.GoalRecord.model_fields.keys()) == (
        "id",
        "user_id",
        "character_id",
        "type",
        "description",
        "priority",
        "status",
        "horizon",
        "source",
        "created_turn",
        "expires_at_turn",
        "created_at",
        "updated_at",
        "parent_goal_id",
        "layer",
        "domain",
        "origin",
        "failure_reason",
        "arbitration_state",
    )


def test_sub_goal_validation_still_rejects_illegal_shapes(make_spec):
    with pytest.raises(ValueError):
        goal_model.validate_sub_goals([make_spec(index=2)])
    with pytest.raises(ValueError):
        goal_model.validate_sub_goals(
            [make_spec(index=1), make_spec(index=2, depends_on=[2])]
        )
    with pytest.raises(ValueError):
        goal_model.validate_sub_goals([make_spec(index=1, parent_index=1)])
    with pytest.raises(ValidationError):
        SubGoalSpec.model_validate(
            {"index": 0, "description": "越界序号", "capability": "c", "criteria": {}}
        )
