"""AUT-003 观察与调整测试。

判据谓词真值表（含不可判定三态）、推进/完成/失败计数幂等、调整三分支
（顺序跳步/触发重规划/goal failed）、执行周期封顶、失败后单次重规划复活、
执行尝试（cooldown/静音/闸门拒绝不计失败/成功落 action 记录）、工作发现
第四来源、Flag OFF 零行为。
"""

from datetime import datetime, timedelta

import pytest

from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.repositories import goal_repository
from app.services import goal_execution, goal_observation
from app.services.goal_planning import TRIGGER_BLOCKED, TRIGGER_REPLAN

NOW = datetime(2026, 9, 8, 12, 0, 0)
USER = "aut3-user"


def _goal(layer="long_term", domain="personal", description="测试目标"):
    return goal_repository.create_hierarchical_goal(USER, layer, domain, description, 3)


def _plan(goal_id, specs, version=1, status="active", updated_at=NOW):
    return goal_repository.create_plan(
        GoalPlanRecord(
            goal_id=goal_id,
            version=version,
            status=status,
            sub_goals=[SubGoalSpec.model_validate(item) for item in specs],
            created_at=NOW,
            updated_at=updated_at,
        )
    )


def _spec(index=1, capability="create_reminder", criteria=None, **overrides):
    base = {
        "index": index,
        "description": f"步骤{index}",
        "capability": capability,
        "params": {},
        "criteria": criteria
        or {"type": "action_succeeded", "capability": capability},
    }
    base.update(overrides)
    return base


def _facts(**overrides):
    facts = {
        "now": NOW,
        "action_results": [],
        "world": {},
        "state": {"tension": 0.5, "intimacy": 0.3, "mood": "calm"},
        "memory": {"salient_memory_count": 2},
    }
    facts.update(overrides)
    return facts


@pytest.fixture()
def aut_on(override_settings, monkeypatch):
    override_settings(
        action_enabled="true",
        world_enabled="false",
        observability_persist_enabled="false")
    yield


class TestEvaluateCriteria:
    def test_action_succeeded_with_window(self):
        criteria = {"type": "action_succeeded", "capability": "create_reminder", "within_minutes": 60}
        old = NOW - timedelta(minutes=90)
        recent = NOW - timedelta(minutes=30)
        facts = _facts(
            action_results=[
                {"capability": "create_reminder", "status": "succeeded", "created_at": old},
            ]
        )
        assert goal_observation.evaluate_criteria(criteria, facts) is False
        facts["action_results"].append(
            {"capability": "create_reminder", "status": "succeeded", "created_at": recent}
        )
        assert goal_observation.evaluate_criteria(criteria, facts) is True

    def test_action_succeeded_ignores_failed(self):
        criteria = {"type": "action_succeeded", "capability": "create_reminder"}
        facts = _facts(
            action_results=[
                {"capability": "create_reminder", "status": "failed", "created_at": NOW}
            ]
        )
        assert goal_observation.evaluate_criteria(criteria, facts) is False

    def test_field_equals_sources(self):
        criteria = {"type": "field_equals", "source": "world", "path": "weather", "value": "rain"}
        assert goal_observation.evaluate_criteria(criteria, _facts(world={"weather": "rain"})) is True
        assert goal_observation.evaluate_criteria(criteria, _facts(world={"weather": "sun"})) is False
        assert goal_observation.evaluate_criteria(criteria, _facts(world={})) is None

    def test_threshold_reached_ops(self):
        criteria = {
            "type": "threshold_reached",
            "source": "state",
            "path": "tension",
            "op": "<=",
            "value": 0.2,
        }
        assert goal_observation.evaluate_criteria(criteria, _facts()) is False
        facts = _facts()
        facts["state"]["tension"] = 0.1
        assert goal_observation.evaluate_criteria(criteria, facts) is True
        facts["state"]["tension"] = None
        assert goal_observation.evaluate_criteria(criteria, facts) is None

    def test_composite_all_of_any_of(self):
        all_of = {
            "type": "all_of",
            "children": [
                {"type": "field_equals", "source": "state", "path": "mood", "value": "calm"},
                {"type": "field_equals", "source": "state", "path": "mood", "value": "sad"},
            ],
        }
        assert goal_observation.evaluate_criteria(all_of, _facts()) is False
        any_of = {
            "type": "any_of",
            "children": [
                {"type": "field_equals", "source": "state", "path": "mood", "value": "calm"},
                {"type": "field_equals", "source": "missing", "path": "x", "value": 1},
            ],
        }
        assert goal_observation.evaluate_criteria(any_of, _facts()) is True


class TestAdvanceGoal:
    def test_criteria_met_advances_without_llm(self, aut_on):
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1), _spec(index=2, capability="query_environment")])
        facts = _facts(
            action_results=[
                {"capability": "create_reminder", "status": "succeeded", "created_at": NOW}
            ]
        )
        detail = goal_observation.advance_goal(goal, plan, facts, NOW)
        assert detail["outcome"] == "advanced"
        assert plan.sub_goals[0].status == "done"
        assert plan.sub_goals[1].status == "pending"

    def test_all_done_completes_and_ingests_experience(self, aut_on):
        goal = _goal()
        plan = _plan(
            goal.id,
            [_spec(index=1, criteria={"type": "field_equals", "source": "state", "path": "mood", "value": "calm"})],
        )
        plan.sub_goals[0].status = "done"
        detail = goal_observation.advance_goal(goal, plan, _facts(), NOW)
        assert detail["outcome"] == "completed"
        assert goal_repository.get_goal(goal.id).status == "completed"
        from app.core.db import MemoryCandidateRow
        from app.services.memory2 import ingest as memory_ingest

        with memory_ingest.SessionLocal() as session:
            row = (
                session.query(MemoryCandidateRow)
                .filter(MemoryCandidateRow.source_table == "character_goals")
                .one()
            )
        assert f"完成了目标：{goal.description}" == row.content

    def test_failure_counts_and_idempotent_per_cycle(self, aut_on):
        goal = _goal()
        plan = _plan(goal.id, [_spec()])
        first = goal_observation.advance_goal(goal, plan, _facts(), NOW)
        assert first["outcome"] == "retrying"
        assert plan.sub_goals[0].attempt_count == 1
        goal_observation.advance_goal(goal, plan, _facts(), NOW)
        assert plan.sub_goals[0].attempt_count == 1
        second = goal_observation.advance_goal(goal, plan, _facts(), NOW + timedelta(minutes=1))
        assert plan.sub_goals[0].attempt_count == 2
        assert second["outcome"] == "retrying"

    def test_criteria_undetermined_skips_without_count(self, aut_on):
        goal = _goal()
        plan = _plan(
            goal.id,
            [_spec(criteria={"type": "field_equals", "source": "world", "path": "weather", "value": "rain"})],
        )
        detail = goal_observation.advance_goal(goal, plan, _facts(), NOW)
        assert detail["outcome"] == "skipped"
        assert plan.sub_goals[0].attempt_count == 0

    def test_threshold_failure_skips_ahead_to_next_step(self, aut_on, override_settings):
        override_settings(autonomy_subgoal_failure_threshold="2")
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1), _spec(index=2, capability="query_environment")])
        goal_observation.advance_goal(goal, plan, _facts(), NOW)
        assert plan.sub_goals[0].attempt_count == 1
        detail = goal_observation.advance_goal(
            goal, plan, _facts(), NOW + timedelta(minutes=1)
        )
        assert detail["outcome"] == "skipped_ahead"
        assert plan.sub_goals[0].status == "failed"
        assert plan.sub_goals[1].status == "pending"

    def test_no_executable_triggers_replan_while_budget_remains(self, aut_on, override_settings):
        override_settings(autonomy_subgoal_failure_threshold="1")
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1)])
        goal_observation.advance_goal(goal, plan, _facts(), NOW)
        detail = goal_observation.advance_goal(goal, plan, _facts(), NOW + timedelta(minutes=1))
        assert detail["outcome"] == "replanning"
        assert any(item.startswith(f"replan:{TRIGGER_BLOCKED}") for item in detail["adjustments"])
        assert goal_repository.get_goal(goal.id).status == "active"

    def test_goal_fails_when_replan_budget_exhausted(self, aut_on, override_settings):
        override_settings(autonomy_subgoal_failure_threshold="1")
        goal = _goal()
        for version in range(1, 3):
            now = datetime.now()
            goal_repository.create_plan(
                GoalPlanRecord(
                    goal_id=goal.id,
                    version=version,
                    status="rejected",
                    rejection_reason="gate",
                    created_at=now,
                    updated_at=now,
                )
            )
        plan = _plan(goal.id, [_spec(index=1)], version=3)
        detail = goal_observation.advance_goal(goal, plan, _facts(), NOW)
        assert detail["outcome"] == "failed"
        assert detail["reason"] == "replan_exhausted"
        record = goal_repository.get_goal(goal.id)
        assert record.status == "failed"
        assert record.failure_reason == "replan_exhausted"

    def test_period_cap_fails_goal(self, aut_on):
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1)], updated_at=NOW - timedelta(hours=200))
        detail = goal_observation.advance_goal(goal, plan, _facts(), NOW)
        assert detail["outcome"] == "failed"
        assert detail["reason"] == "exec_period_exceeded"
        record = goal_repository.get_goal(goal.id)
        assert record.status == "failed"
        assert record.failure_reason == "exec_period_exceeded"


    def test_advance_user_goals_without_plans(self, aut_on):
        result = goal_observation.advance_user_goals(USER, _facts(), NOW)
        assert result == {"status": "ok", "goals": 0, "results": []}


class TestFailureReplanReactivation:
    def test_failed_goal_single_replan_reactivates(self, aut_on, override_settings, monkeypatch):
        override_settings(
            autonomy_subgoal_failure_threshold="1",
            autonomy_planning_max_attempts="2",
        )
        goal = _goal()
        now = datetime.now()
        goal_repository.create_plan(
            GoalPlanRecord(
                goal_id=goal.id,
                version=1,
                status="rejected",
                rejection_reason="gate",
                created_at=now,
                updated_at=now,
            )
        )
        plan_two = _plan(goal.id, [_spec(index=1)], version=2)
        detail = goal_observation.advance_goal(goal, plan_two, _facts(), NOW)
        assert detail["outcome"] == "failed"
        record = goal_repository.get_goal(goal.id)
        assert record.status == "failed"
        assert record.failure_reason == "replan_exhausted"

        from app.services import goal_planning

        monkeypatch.setattr(
            goal_planning,
            "_ask_llm_with_retry",
            lambda messages, settings: goal_planning.PlanningProposal(
                sub_goals=[_spec(index=1)]
            ),
        )
        outcome = goal_planning.plan_goal(goal.id, TRIGGER_REPLAN)
        assert outcome["status"] == "ok"
        assert outcome["version"] == 3
        assert goal_repository.get_goal(goal.id).status == "active"
        assert goal_repository.count_plans(goal.id) == 3

        third = goal_planning.plan_goal(goal.id, TRIGGER_REPLAN)
        assert third["status"] == "rejected"
        assert third["reason"] == "attempt_cap"


def _planning_jobs():
    from app.repositories import background_job_repository

    return background_job_repository.list_jobs("goal_planning")


class TestExecutionAttempt:
    def test_action_disabled_skips(self, override_settings):
        override_settings( action_enabled="false")
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1)])
        result = _run_attempt(goal, plan)
        assert result["skip_reason"] == "action_disabled"

    def test_cooldown_skips_second_attempt(self, aut_on, monkeypatch):
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1)])
        _stub_run_planning(monkeypatch, "succeeded")
        first = _run_attempt(goal, plan)
        assert first["status"] == "ok"
        second = _run_attempt(goal, plan)
        assert second["skip_reason"] == "cooldown"

    def test_gate_refusal_not_counted_as_failure(self, aut_on, monkeypatch):
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1)])
        _stub_run_planning(monkeypatch, None)
        result = _run_attempt(goal, plan)
        assert result["status"] == "gated"
        assert plan.sub_goals[0].attempt_count == 0
        assert plan.sub_goals[0].last_attempt_at == NOW

    def test_success_records_action(self, aut_on, monkeypatch):
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1)])
        _stub_run_planning(monkeypatch, "succeeded")
        result = _run_attempt(goal, plan)
        assert result["status"] == "ok"
        assert result["action_status"] == "succeeded"
        assert plan.sub_goals[0].last_attempt_at == NOW

    def test_notification_quiet_hours_skipped(self, aut_on):
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1, capability="send_notification")])
        quiet_now = datetime(2026, 9, 8, 23, 30, 0)
        import asyncio

        result = asyncio.run(goal_execution.attempt_current_step(goal, plan, quiet_now))
        assert result["skip_reason"] == "quiet_hours"


def _run_attempt(goal, plan):
    import asyncio

    return asyncio.run(goal_execution.attempt_current_step(goal, plan, NOW))


def _stub_run_planning(monkeypatch, status):
    from app.models.action import ActionRecord

    async def _fake(user_id, intent, session_id=None, goal_id=None, source="conversation"):
        if status is None:
            return None
        return ActionRecord(
            id="act-1",
            user_id=user_id,
            action_type=intent.action_type,
            status=status,
            goal_id=goal_id,
        )

    import app.application.action_engine as action_engine

    monkeypatch.setattr(action_engine, "run_action_planning", _fake)


class TestWorkDiscovery:
    def test_goal_work_due_user_discovered(self, aut_on):
        from app.application import life_loop
        from app.repositories import conversation_repository

        conversation_repository.get_or_create_conversation("aut3-s1", USER)
        goal = _goal()
        _plan(goal.id, [_spec(index=1)])
        users = life_loop._collect_work_users(NOW)
        assert users == [USER]
        assert life_loop._cycle_reason(USER, NOW) == "goal_work"

    def test_goal_work_cooldown_not_due(self, aut_on, override_settings):
        from app.application import life_loop

        override_settings(autonomy_subgoal_execute_cooldown_minutes="60")
        goal = _goal()
        plan = _plan(goal.id, [_spec(index=1)])
        plan.sub_goals[0].last_attempt_at = NOW - timedelta(minutes=10)
        goal_repository.update_plan_progress(plan.id, plan.sub_goals)
        assert life_loop._goal_work_due(USER, NOW) is False


    def test_advance_step_no_plans_is_noop(self, aut_on):
        from app.application import life_loop
        import asyncio

        result = asyncio.run(life_loop._step_goal_advance(USER, NOW))
        assert result == {"status": "ok", "goals": 0, "observations": 0, "executions": 0}


def test_trace_step_registered():
    from app.services.trace_collector import TRACE_STEP_NAMES

    assert "goal_observation" in TRACE_STEP_NAMES
