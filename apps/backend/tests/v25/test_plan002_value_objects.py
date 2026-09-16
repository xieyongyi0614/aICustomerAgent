"""PLAN-002 U1~U3：计划域值对象（序列化往返 / 非法值负例 / 派生属性 / 硬依赖字段）。

口径与 PLAN-001 一致：期望值写死为字面量，被测源码与快照的任何差异都会让用例失败。
"""

from datetime import datetime
from typing import get_args

import pytest
from pydantic import ValidationError

from app.models.goal import GoalRecord, ON_FAILURE_MODES, RETRY_MODES, STEP_KINDS
from app.models.plan import (
    ON_FAILURE_MODE_VALUES,
    PLAN_ADVANCE_DECISIONS,
    PLAN_ADVANCE_DECISION_VALUES,
    PLAN_ADVANCE_TERMINAL_DECISIONS,
    PLAN_REVISION_REASONS,
    PLAN_REVISION_REASON_VALUES,
    PLAN_STEP_OUTCOMES,
    PLAN_STEP_OUTCOME_VALUES,
    RETRY_MODE_VALUES,
    STEP_KIND_VALUES,
    GoalRef,
    MemoryRef,
    PlanAdvance,
    PlanAdvanceDecision,
    PlanContext,
    PlanRevision,
    PlanRevisionReason,
    PlanStepBinding,
    PlanStepOutcome,
    PlanStepOutcomeStatus,
    PlanValidationReport,
    RetryPolicy,
)
from app.models.tool import (
    TOOL_EFFECT_KINDS,
    TOOL_FAILURE_KINDS,
    PermissionProfile,
    ToolBinding,
    ToolDefinition,
    ToolSchema,
    ToolSurface,
)

NOW = datetime(2026, 9, 8, 12, 0, 0)

TOOL_ID = "builtin.reminder.create"

VALUE_SET_SNAPSHOT = {
    "PlanStepOutcomeStatus": (
        "succeeded",
        "failed",
        "timeout",
        "blocked",
        "skipped",
        "hold",
    ),
    "PlanAdvanceDecision": (
        "advanced",
        "completed",
        "failed",
        "replanning",
        "skipped",
        "hold",
    ),
    "PlanRevisionReason": (
        "step_attempt_exhausted",
        "tool_persistently_unavailable",
        "criteria_undecidable",
        "insight_driven",
    ),
}

TUPLE_SNAPSHOT = {
    "PLAN_STEP_OUTCOMES": VALUE_SET_SNAPSHOT["PlanStepOutcomeStatus"],
    "PLAN_ADVANCE_DECISIONS": VALUE_SET_SNAPSHOT["PlanAdvanceDecision"],
    "PLAN_REVISION_REASONS": VALUE_SET_SNAPSHOT["PlanRevisionReason"],
    "PLAN_ADVANCE_TERMINAL_DECISIONS": ("completed", "failed", "skipped"),
    "STEP_KINDS": ("tool", "observe", "composite"),
    "RETRY_MODES": ("none", "once", "until_budget"),
    "ON_FAILURE_MODES": ("abort", "skip", "replan", "continue"),
}

FROZENSET_SNAPSHOT = {
    "PLAN_STEP_OUTCOME_VALUES": VALUE_SET_SNAPSHOT["PlanStepOutcomeStatus"],
    "PLAN_ADVANCE_DECISION_VALUES": VALUE_SET_SNAPSHOT["PlanAdvanceDecision"],
    "PLAN_REVISION_REASON_VALUES": VALUE_SET_SNAPSHOT["PlanRevisionReason"],
    "STEP_KIND_VALUES": ("tool", "observe", "composite"),
    "RETRY_MODE_VALUES": ("none", "once", "until_budget"),
    "ON_FAILURE_MODE_VALUES": ("abort", "skip", "replan", "continue"),
}


def tool_definition() -> ToolDefinition:
    return ToolDefinition(
        id=TOOL_ID,
        name="创建提醒",
        description="为用户创建一个提醒",
        namespace="builtin",
        capability="create_reminder",
        action="create",
        input_schema=ToolSchema(),
        permission=PermissionProfile(level="normal"),
    )


def tool_surface() -> ToolSurface:
    return ToolSurface(
        run_kind="autonomous_tick",
        tool_ids=(TOOL_ID,),
        excluded=({"tool_id": "ext.api.weather.query", "reason": "off_surface"},),
        surface_hash="9f2c",
    )


def goal_record() -> GoalRecord:
    return GoalRecord(
        id="goal-1",
        user_id="plan2-user",
        type="user_care",
        description="提醒用户休息",
        priority=3,
        layer="long_term",
        domain="personal",
        created_at=NOW,
        updated_at=NOW,
    )


def test_u1_value_sets_are_frozen():
    import app.models.plan as plan_model

    for name, expected in VALUE_SET_SNAPSHOT.items():
        assert get_args(getattr(plan_model, name)) == expected, name
    for name, expected in TUPLE_SNAPSHOT.items():
        assert getattr(plan_model, name) == expected, name
    for name, expected in FROZENSET_SNAPSHOT.items():
        assert getattr(plan_model, name) == frozenset(expected), name
    assert STEP_KINDS == TUPLE_SNAPSHOT["STEP_KINDS"]
    assert RETRY_MODES == TUPLE_SNAPSHOT["RETRY_MODES"]
    assert ON_FAILURE_MODES == TUPLE_SNAPSHOT["ON_FAILURE_MODES"]


def test_u1_frozensets_are_derived_from_the_literals():
    assert PLAN_STEP_OUTCOME_VALUES == frozenset(get_args(PlanStepOutcomeStatus))
    assert PLAN_ADVANCE_DECISION_VALUES == frozenset(get_args(PlanAdvanceDecision))
    assert PLAN_REVISION_REASON_VALUES == frozenset(get_args(PlanRevisionReason))


def test_u1_terminal_decisions_are_a_subset_of_the_decision_value_set():
    assert set(PLAN_ADVANCE_TERMINAL_DECISIONS) < set(PLAN_ADVANCE_DECISIONS)
    assert "advanced" not in PLAN_ADVANCE_TERMINAL_DECISIONS
    assert "replanning" not in PLAN_ADVANCE_TERMINAL_DECISIONS
    assert "hold" not in PLAN_ADVANCE_TERMINAL_DECISIONS


def test_u1_retry_policy_round_trip():
    policy = RetryPolicy(mode="until_budget", max_attempts=2)
    dumped = policy.model_dump(mode="json")
    assert dumped == {"mode": "until_budget", "max_attempts": 2}
    assert RetryPolicy.model_validate(dumped) == policy


def test_u1_plan_step_binding_round_trip_keeps_nested_tool_binding():
    binding = ToolBinding(
        tool_id=TOOL_ID,
        capability="create_reminder",
        action="create",
        definition=tool_definition(),
    )
    value = PlanStepBinding(
        step_index=2, binding=binding, binding_reason="tool_selector"
    )
    dumped = value.model_dump(mode="json")
    assert dumped["binding"]["definition"]["id"] == TOOL_ID
    restored = PlanStepBinding.model_validate(dumped)
    assert restored == value
    assert restored.binding.definition.namespace == "builtin"


def test_u1_plan_step_outcome_round_trip_keeps_observation_payload():
    outcome = PlanStepOutcome(
        step_index=1,
        status="succeeded",
        at=NOW,
        action_id="action-1",
        tool_id=TOOL_ID,
        failure_kind=None,
        attempt=1,
        effects=[{"kind": "note", "ref": "note-1", "reversible": True}],
        observations={"reminder_id": "rem-1", "channel": "feishu"},
        criteria_result=True,
        duration_ms=42,
    )
    dumped = outcome.model_dump(mode="json")
    assert dumped["at"] == NOW.isoformat()
    assert PlanStepOutcome.model_validate(dumped) == outcome


def test_u1_plan_step_outcome_failure_kind_reuses_tool_failure_kinds():
    assert len(TOOL_FAILURE_KINDS) == 6
    for kind in TOOL_FAILURE_KINDS:
        assert PlanStepOutcome(step_index=1, status="failed", at=NOW, failure_kind=kind)
    with pytest.raises(ValidationError):
        PlanStepOutcome(step_index=1, status="failed", at=NOW, failure_kind="whatever")


def test_u1_plan_advance_round_trip():
    advance = PlanAdvance(
        goal_id="goal-1",
        plan_id="plan-1",
        plan_version=2,
        decision="advanced",
        reason="步骤 1 达成判据，推进到步骤 2",
        step_index=1,
        facts_digest={"action_succeeded": ["create_reminder"]},
        at=NOW,
    )
    dumped = advance.model_dump(mode="json")
    assert PlanAdvance.model_validate(dumped) == advance
    assert dumped["reason"] == "步骤 1 达成判据，推进到步骤 2"


def test_u1_plan_revision_round_trip():
    revision = PlanRevision(
        from_version=1,
        to_version=2,
        reason="insight_driven",
        trigger_source="insight_driven",
        evidence_refs=["insight-1", "memory-9"],
        kept_steps=[1],
        at=NOW,
    )
    dumped = revision.model_dump(mode="json")
    assert dumped["kept_steps"] == [1]
    assert PlanRevision.model_validate(dumped) == revision


def test_u1_plan_context_round_trip():
    context = PlanContext(
        goal=goal_record(),
        tool_surface=tool_surface(),
        budget={"max_steps": 5, "max_depth": 2, "revision_budget": 3, "max_attempts": 2},
        ancestors=[
            GoalRef(
                id="goal-0",
                type="user_care",
                status="active",
                layer="long_term",
                domain="personal",
                priority=4,
            )
        ],
        siblings=[GoalRef(id="goal-2", type="relationship", status="active")],
        world={"weather": "rain"},
        relationship={"stage": "close_friend", "tension": 0.2},
        memories=[
            MemoryRef(
                id="memory-1", type="user_fact", content="用户常熬夜", importance=0.8
            )
        ],
        run={"run_id": "run-1", "run_kind": "autonomous_tick"},
        degraded=["world_context"],
        evidence_refs=["insight-1"],
    )
    dumped = context.model_dump(mode="json")
    assert dumped["tool_surface"]["surface_hash"] == "9f2c"
    assert dumped["goal"]["id"] == "goal-1"
    restored = PlanContext.model_validate(dumped)
    assert restored == context
    assert isinstance(restored.goal, GoalRecord)
    assert isinstance(restored.tool_surface, ToolSurface)


def test_u1_plan_context_optional_sources_default_to_empty():
    context = PlanContext(
        goal=goal_record(), tool_surface=tool_surface(), budget={"max_steps": 5}
    )
    assert context.ancestors == []
    assert context.siblings == []
    assert context.memories == []
    assert context.insights == []
    assert context.situations == []
    assert context.degraded == []
    assert context.evidence_refs == []
    assert context.world_brief is None
    assert context.world_context is None
    assert context.scene is None


def test_u1_plan_context_hard_dependencies_are_required():
    with pytest.raises(ValidationError):
        PlanContext(tool_surface=tool_surface(), budget={})
    with pytest.raises(ValidationError):
        PlanContext(goal=goal_record(), budget={})
    with pytest.raises(ValidationError):
        PlanContext(goal=goal_record(), tool_surface=tool_surface())


def test_u1_goal_ref_priority_stays_inside_the_goal_priority_band():
    with pytest.raises(ValidationError):
        GoalRef(id="goal-x", type="user_care", status="active", priority=0)
    with pytest.raises(ValidationError):
        GoalRef(id="goal-x", type="user_care", status="active", priority=6)


def test_u2_plan_step_outcome_status_outside_the_six_values_is_rejected():
    with pytest.raises(ValidationError):
        PlanStepOutcome(step_index=1, status="whatever", at=NOW)
    with pytest.raises(ValidationError):
        PlanStepOutcome(step_index=0, status="succeeded", at=NOW)


def test_u2_retry_policy_mode_outside_the_three_values_is_rejected():
    with pytest.raises(ValidationError):
        RetryPolicy(mode="always")
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=-1)


def test_u2_plan_advance_decision_outside_the_six_values_is_rejected():
    with pytest.raises(ValidationError):
        PlanAdvance(
            goal_id="goal-1",
            plan_id="plan-1",
            plan_version=1,
            decision="x",
            reason="非法裁决",
            at=NOW,
        )


def test_u2_plan_advance_reason_is_capped_at_sixty_characters():
    PlanAdvance(
        goal_id="goal-1",
        plan_id="plan-1",
        plan_version=1,
        decision="hold",
        reason="推" * 60,
        at=NOW,
    )
    with pytest.raises(ValidationError):
        PlanAdvance(
            goal_id="goal-1",
            plan_id="plan-1",
            plan_version=1,
            decision="hold",
            reason="推" * 61,
            at=NOW,
        )


def test_u2_plan_revision_reason_outside_the_four_codes_is_rejected():
    with pytest.raises(ValidationError):
        PlanRevision(
            from_version=1,
            to_version=2,
            reason="x",
            trigger_source="insight_driven",
            at=NOW,
        )
    with pytest.raises(ValidationError):
        PlanRevision(
            from_version=1,
            to_version=2,
            reason="insight_driven",
            trigger_source="x",
            at=NOW,
        )


def test_u3_plan_validation_report_passed_is_derived_from_the_three_error_sets():
    assert PlanValidationReport().passed is True
    assert PlanValidationReport(shape_errors=["序号不连续"]).passed is False
    assert PlanValidationReport(surface_errors=["工具不在面上"]).passed is False
    assert PlanValidationReport(budget_errors=["超过步数上限"]).passed is False


def test_u3_plan_validation_report_is_read_only_and_not_persisted():
    report = PlanValidationReport(shape_errors=["父引用缺失"])
    assert "passed" not in report.model_dump()
    assert set(report.model_dump()) == {"shape_errors", "surface_errors", "budget_errors"}


def test_u3_plan_advance_is_terminal_covers_exactly_the_settled_decisions():
    def advance(decision: str) -> PlanAdvance:
        return PlanAdvance(
            goal_id="goal-1",
            plan_id="plan-1",
            plan_version=1,
            decision=decision,
            reason="裁决",
            at=NOW,
        )

    for decision in PLAN_ADVANCE_TERMINAL_DECISIONS:
        assert advance(decision).is_terminal is True, decision
    for decision in ("advanced", "replanning", "hold"):
        assert advance(decision).is_terminal is False, decision


def test_u3_retry_policy_is_bounded_only_when_the_bound_is_local():
    assert RetryPolicy(mode="none", max_attempts=0).is_bounded is True
    assert RetryPolicy(mode="once", max_attempts=1).is_bounded is True
    assert RetryPolicy(mode="until_budget", max_attempts=2).is_bounded is False


def test_u3_retry_policy_defaults_follow_the_once_semantics():
    policy = RetryPolicy()
    assert (policy.mode, policy.max_attempts) == ("once", 1)
    assert RetryPolicy.model_fields["mode"].default == "once"


def test_expected_effects_value_set_matches_tool_effect_kinds():
    assert len(TOOL_EFFECT_KINDS) == 5
    assert set(TOOL_EFFECT_KINDS) == {
        "world",
        "memory",
        "relationship",
        "note",
        "external",
    }


def test_plan_domain_module_exports_the_declared_surface():
    import app.models.plan as plan_model

    missing = [
        name
        for name in plan_model.__all__
        if not hasattr(plan_model, name)
    ]
    assert missing == []
    for name in (
        "PlanContext",
        "PlanStepBinding",
        "PlanStepOutcome",
        "PlanAdvance",
        "PlanRevision",
        "PlanValidationReport",
        "RetryPolicy",
        "GoalRef",
        "MemoryRef",
    ):
        assert name in plan_model.__all__, name
