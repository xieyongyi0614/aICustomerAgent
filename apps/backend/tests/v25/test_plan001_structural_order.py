"""PLAN-001 Step 5 / §9.3 S1、S4：结构序优先于目标优先级（priority vs 结构序）。

既有结构序的可判定形态：`goal_observation._execution_order` 由父子与声明顺序决定，
`_current_step` 只取其中第一个未完成步，**全程不读** `goal.priority` 与 `GOAL_TIER`
（因此「高 tier / 高 priority 目标的后继步骤不越过其前驱」在今日即可判定）。

`PlanScheduler.order`（PLAN-005 落地）上的同款断言见 `test_plan001_deferred.py`。
"""

from datetime import timedelta

from app.repositories import goal_repository
from app.services.goal import observation as goal_observation

from .conftest import V25_NOW

PREDECESSOR_STEP = {
    "index": 1,
    "description": "先确认环境",
    "capability": "query_environment",
    "params": {},
    "criteria": {"type": "action_succeeded", "capability": "query_environment"},
}

SUCCESSOR_STEP = {
    "index": 2,
    "description": "再推送提醒",
    "capability": "create_reminder",
    "params": {"content": "该休息了"},
    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    "depends_on": [1],
}

DEPENDENT_PLAN = (PREDECESSOR_STEP, SUCCESSOR_STEP)

HIGH_TIER_DOMAIN = "world"

NEXT_TICK = V25_NOW + timedelta(minutes=5)


def _specs() -> list[dict]:
    return [dict(step) for step in DEPENDENT_PLAN]


def _advance(make_goal, make_plan, goal_facts, goal_options):
    goal = make_goal(description=f"结构序目标{goal_options['priority']}", **goal_options)
    plan = make_plan(goal.id, _specs())
    facts = goal_facts(succeeded=["create_reminder"])
    detail = goal_observation.advance_goal(goal, plan, facts, V25_NOW)
    reloaded = goal_repository.get_plan(plan.id)
    return {
        "outcome": detail["outcome"],
        "observed": detail["observations"],
        "statuses": [spec.status for spec in reloaded.sub_goals],
        "attempts": [spec.attempt_count for spec in reloaded.sub_goals],
    }


def test_successor_never_overtakes_its_predecessor(make_goal, make_plan, goal_facts):
    result = _advance(
        make_goal,
        make_plan,
        goal_facts,
        {"priority": 5, "domain": HIGH_TIER_DOMAIN},
    )
    assert result["observed"] == 1
    assert result["statuses"] == ["in_progress", "pending"]
    assert result["attempts"] == [1, 0]


def test_successor_is_observed_only_after_its_predecessor_is_done(
    make_goal, make_plan, goal_facts
):
    goal = make_goal(description="依赖链目标", priority=5, domain=HIGH_TIER_DOMAIN)
    plan = make_plan(goal.id, _specs())
    first = goal_observation.advance_goal(
        goal, plan, goal_facts(succeeded=["query_environment"]), V25_NOW
    )
    assert first["outcome"] == "advanced"
    after_first = goal_repository.get_plan(plan.id)
    assert [spec.status for spec in after_first.sub_goals] == ["done", "pending"]
    assert after_first.sub_goals[1].attempt_count == 0

    second = goal_observation.advance_goal(
        goal, after_first, goal_facts(succeeded=["create_reminder"]), NEXT_TICK
    )
    assert second["outcome"] == "completed"
    after_second = goal_repository.get_plan(plan.id)
    assert [spec.status for spec in after_second.sub_goals] == ["done", "done"]
    assert goal_repository.get_goal(goal.id).status == "completed"


def test_goal_priority_and_tier_do_not_reorder_steps(make_goal, make_plan, goal_facts):
    lowest = _advance(
        make_goal, make_plan, goal_facts, {"priority": 1, "domain": "personal"}
    )
    highest = _advance(
        make_goal,
        make_plan,
        goal_facts,
        {"priority": 5, "domain": HIGH_TIER_DOMAIN},
    )
    assert lowest == highest


def test_same_dependent_plan_runs_identically_across_goal_types(
    make_goal, make_plan, goal_facts
):
    outcomes = {
        domain: tuple(
            _advance(
                make_goal, make_plan, goal_facts, {"priority": 3, "domain": domain}
            )["statuses"]
        )
        for domain in ("personal", "relationship", "world")
    }
    assert len(outcomes) == 3
    assert set(outcomes.values()) == {("in_progress", "pending")}
