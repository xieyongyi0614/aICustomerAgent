"""PLAN-001 Step 4：四条联动不变量的可判定用例（Task Detail §4.4 / §9.2 I1~I7）。

- I1：计划状态不得单独改写 `GoalStatus`——必须经唯一写面且符合迁移表。
- I2：`GoalStatus` 终态时其计划不得再被推进（冻结形态，今日成立；进终态形态见 deferred）。
- I3（= I5）：同一 `goal_id` 同一时刻最多一个 `active` 计划。
- I4：同一 `(layer, domain)` 顶层 `active` 目标 ≤ 1（引用既有 `GoalArbitrationRule`，不重写）。
- I6：优先级算法调用点唯一 → 静态断言，见 `test_plan001_static_scan.py`。
- I7：Planning 触达 `character_goals` 的写操作只经 §6.2 五个函数。
"""

import pytest

from app.models.evaluation import IssueCode
from app.repositories import goal_repository
from app.services import goal_observation, goal_planning
from app.services.evaluation_context import EvaluationContext, collect_goal_slice
from app.services.evaluation_rules.goal import GoalArbitrationRule
from app.services.planning import goal_contract

from .conftest import V25_NOW, V25_USER


def test_i1_rejected_plan_leaves_goal_active(make_goal, make_plan):
    goal = make_goal()
    plan = make_plan(goal.id)
    rejected = goal_repository.set_plan_rejection(plan.id, "invalid_sub_goal_shape")
    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "invalid_sub_goal_shape"
    reloaded = goal_repository.get_goal(goal.id)
    assert (reloaded.status, reloaded.failure_reason) == ("active", None)


def test_i1_superseded_plan_leaves_goal_active(make_goal, make_plan):
    goal = make_goal()
    older = make_plan(goal.id, version=1)
    newer = make_plan(goal.id, version=2, status="validated")
    goal_repository.set_plan_status(older.id, "superseded")
    goal_repository.set_plan_status(newer.id, "active")
    assert goal_repository.get_goal(goal.id).status == "active"
    assert goal_repository.get_latest_plan(goal.id).version == 2


def test_i1_plan_writes_never_touch_goal_status(make_goal, make_plan):
    goal = make_goal()
    plan = make_plan(goal.id, status="draft")
    statuses = ("validated", "active", "superseded", "rejected")
    for status in statuses:
        goal_repository.set_plan_status(plan.id, status)
        assert goal_repository.get_goal(goal.id).status == "active", status
    assert goal_repository.get_plan(plan.id).status == "rejected"


def test_i1_illegal_transition_is_refused_by_the_single_write_face(make_goal):
    active = make_goal(description="非法迁移用例")
    with pytest.raises(ValueError):
        goal_repository.set_status(active.id, "expired")
    with pytest.raises(ValueError):
        goal_repository.finish_goal(active.id, "expired")
    assert goal_repository.get_goal(active.id).status == "active"


def test_i1_settled_goal_ignores_further_terminal_requests(make_goal):
    goal = make_goal(description="已终态用例")
    goal_repository.complete_goal(goal.id)
    with pytest.raises(ValueError):
        goal_repository.set_status(goal.id, "active")
    assert goal_repository.finish_goal(goal.id, "suspended").status == "completed"
    assert goal_repository.fail_goal(goal.id, "plan_exhausted").status == "completed"
    assert goal_repository.reactivate_goal(goal.id).status == "completed"
    assert goal_repository.set_status(goal.id, "completed").status == "completed"
    reloaded = goal_repository.get_goal(goal.id)
    assert (reloaded.status, reloaded.failure_reason) == ("completed", None)


def test_i2_terminal_goal_stops_advancing_its_plan(
    make_goal, make_plan, goal_facts, autonomy_on
):
    assert autonomy_on
    goal = make_goal()
    plan = make_plan(goal.id)
    facts = goal_facts(succeeded=["create_reminder"])
    detail = goal_observation.advance_goal(goal, plan, facts, V25_NOW)
    assert detail["outcome"] == "completed"
    assert goal_repository.get_goal(goal.id).status == "completed"
    assert goal_repository.list_active_plans(V25_USER) == []
    assert goal_observation.advance_user_goals(V25_USER, facts, V25_NOW) == {
        "status": "ok",
        "goals": 0,
        "results": [],
    }


def test_i2_failed_goal_records_plan_exhausted_and_leaves_candidates(
    make_goal, make_plan, goal_facts, autonomy_on
):
    assert autonomy_on
    goal = make_goal()
    make_plan(goal.id)
    goal_repository.fail_goal(
        goal.id, goal_contract.PLANNING_FAILURE_REASON_PLAN_EXHAUSTED
    )
    reloaded = goal_repository.get_goal(goal.id)
    assert (reloaded.status, reloaded.failure_reason) == ("failed", "plan_exhausted")
    assert goal_repository.list_active_plans(V25_USER) == []
    assert goal_observation.advance_user_goals(V25_USER, goal_facts(), V25_NOW)["goals"] == 0


def test_i2_planning_failure_reason_terms_need_no_ddl(make_goal):
    goal = make_goal(description="词表写库用例")
    recorded = goal_repository.fail_goal(
        goal.id, goal_contract.PLANNING_FAILURE_REASON_CRITERIA_UNDECIDABLE
    )
    assert recorded.failure_reason == "criteria_undecidable"
    assert goal_repository.get_goal(goal.id).status == "failed"


def test_i3_only_one_active_plan_survives_a_second_version(
    make_goal, autonomy_on, stub_planning_llm
):
    assert autonomy_on
    goal = make_goal()
    stub_planning_llm()
    first = goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)
    second = goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_REPLAN)
    assert (first["status"], second["status"]) == ("ok", "ok")
    plans = goal_repository.list_plans(goal.id)
    assert [plan.version for plan in plans] == [2, 1]
    assert [plan.status for plan in plans] == ["active", "superseded"]
    assert sum(1 for plan in plans if plan.status == "active") <= 1


def test_i3_repeated_created_trigger_does_not_open_a_second_active_plan(
    make_goal, autonomy_on, stub_planning_llm
):
    assert autonomy_on
    goal = make_goal()
    stub_planning_llm()
    assert goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)["status"] == "ok"
    again = goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)
    assert again == {"status": "skipped", "skip_reason": "plan_exists"}
    plans = goal_repository.list_plans(goal.id)
    assert sum(1 for plan in plans if plan.status == "active") == 1


def _goal_slice_context() -> EvaluationContext:
    return EvaluationContext(
        subject="goal",
        subject_id="plan1-slice",
        session_id="",
        user_id=V25_USER,
        goal=collect_goal_slice(V25_USER),
    )


def test_i4_same_domain_second_top_level_active_goal_is_reported(make_goal):
    make_goal(description="同域目标甲")
    make_goal(description="同域目标乙")
    issue = GoalArbitrationRule().evaluate(_goal_slice_context())
    assert issue is not None
    assert issue.code == IssueCode.GOAL_ARBITRATION_MISSING
    assert "personal" in issue.evidence_quote


def test_i4_single_top_level_active_goal_passes_the_same_rule(make_goal):
    make_goal(description="独占目标")
    assert GoalArbitrationRule().evaluate(_goal_slice_context()) is None


def test_i4_rule_is_owned_by_the_existing_evaluation_layer():
    assert GoalArbitrationRule.__module__ == "app.services.evaluation_rules.goal"
    assert GoalArbitrationRule.__name__ == "GoalArbitrationRule"
    assert GoalArbitrationRule.subjects == ("goal",)


def test_i7_every_write_entry_passes_the_transition_guard(make_goal, monkeypatch):
    hits: list[str] = []
    original = goal_repository.goal_transitions
    monkeypatch.setattr(
        goal_repository,
        "goal_transitions",
        lambda layer, current: (hits.append(current), original(layer, current))[1],
    )
    cases = (
        (lambda goal: goal_repository.set_status(goal.id, "completed"), "active"),
        (lambda goal: goal_repository.finish_goal(goal.id, "failed", "plan_exhausted"), "active"),
        (lambda goal: goal_repository.complete_goal(goal.id), "active"),
        (lambda goal: goal_repository.fail_goal(goal.id, "plan_exhausted"), "active"),
    )
    for index, (action, expected) in enumerate(cases, start=1):
        before = len(hits)
        action(make_goal(description=f"写面用例{index}"))
        assert hits[before:] == [expected]
    before = len(hits)
    failed = make_goal(description="复活用例")
    goal_repository.fail_goal(failed.id, "plan_exhausted")
    goal_repository.reactivate_goal(failed.id)
    assert hits[before:] == ["active", "failed"]
    assert goal_repository.get_goal(failed.id).status == "active"


def test_i7_declaration_layer_exposes_constants_only():
    public = sorted(name for name in vars(goal_contract) if not name.startswith("_"))
    assert public
    assert [name for name in public if not name.isupper()] == []
    names = goal_contract.PLANNING_WRITE_FUNCTION_NAMES
    assert names == tuple(name for _, name in goal_contract.PLANNING_WRITE_INTERFACES)
    assert len(names) == 5
    assert [name for name in names if name != name.lower()] == []


def test_i7_plan_face_and_state_face_are_distinct_surfaces(make_goal, make_plan):
    goal = make_goal()
    plan = make_plan(goal.id)
    goal_repository.update_plan_progress(plan.id, plan.sub_goals)
    assert goal_repository.get_goal(goal.id).status == "active"
    assert goal_repository.get_plan(plan.id).sub_goals[0].status == "pending"
