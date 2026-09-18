"""PLAN-012 场景集 A：单目标规划（判据 A 两侧 + 每步绑定与判据可判定）。

版本级扇入：组合 PLAN-003（规划引擎）+ PLAN-004（三闸）+ PLAN-009（判据 A），
不重复各任务内部的细粒度断言。
"""

import pytest

from app.models.plan import PlanContext
from app.models.tool import ToolSurface
from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.models.goal import SubGoalSpec
from app.repositories import goal_repository
from app.services import goal_planning
from app.services.planning import context as plan_context
from app.services.planning import memory_policy as plan_memory_policy
from app.services.planning.decompose import PlanValidator
from app.services.planning.engine import PLAN_STATUS_VALIDATED, PlanningEngine
from app.core.settings import get_settings

from . import plan012_support as support
from .plan004_support import DEFAULT_BUDGET

BUDGET = dict(DEFAULT_BUDGET)
BUDGET["ttl_hours"] = 168
BUDGET["goal_max_active_hours"] = 168


class TestScenarioASingleGoal:
    """S1：active Goal → validated 多步计划；每步 tool_id 与判据可判定。"""

    @pytest.mark.asyncio
    async def test_multi_step_goal_produces_a_validated_plan_with_bindings(
        self, db_session_factory, override_settings, make_goal, stub_planning_llm
    ):
        override_settings(
            planning_enabled="true",
            plan_context_enabled="true",
            plan_step_binding_enabled="true",
            tool_system_enabled="true",
            world_enabled="false",
            observability_persist_enabled="false")
        steps = [
            {
                "index": 1,
                "description": "记下面试安排",
                "capability": "remember_fact",
                "params": {"fact": "后天有面试"},
                "criteria": {
                    "type": "action_succeeded",
                    "capability": "remember_fact",
                },
                "tool_id": support.MEMORY_SAVE,
            },
            {
                "index": 2,
                "description": "提前一晚提醒",
                "capability": "create_reminder",
                "params": {"content": "明天面试", "due_at": "2026-09-17T20:00:00"},
                "criteria": {
                    "type": "action_succeeded",
                    "capability": "create_reminder",
                },
                "tool_id": support.REMINDER_CREATE,
            },
        ]
        stub_planning_llm(steps)
        goal = make_goal(description="面试准备目标", layer="short_term")
        engine = PlanningEngine()
        ctx = PlanContext(
            goal=goal,
            tool_surface=ToolSurface(
                run_kind=RUN_KIND_AUTONOMOUS_TICK,
                tool_ids=(support.MEMORY_SAVE, support.REMINDER_CREATE),
            ),
            budget=plan_context.plan_budget(get_settings()),
        )

        outcome = await engine.plan(goal, ctx, trigger=goal_planning.TRIGGER_CREATED)

        assert outcome.status == PLAN_STATUS_VALIDATED, outcome.rejection_reason
        assert outcome.plan is not None
        assert len(outcome.plan.sub_goals) == 2
        stored = goal_repository.get_latest_plan(goal.id)
        assert stored is not None
        assert len(stored.sub_goals) == 2

    def test_judgement_a_persists_this_multi_step_interview_plan(self):
        assert plan_memory_policy.should_persist_plan(
            step_count=4,
            cross_tick=True,
            every_step_has_criteria=True,
            needs_idempotency_or_recovery=True,
        )

    def test_judgement_a_direct_passes_for_instant_single_step(self):
        """单步当场可验 → 不落计划结构（判据 A 侧）。"""
        assert plan_memory_policy.should_persist_plan(
            step_count=1,
            cross_tick=False,
            every_step_has_criteria=True,
            needs_idempotency_or_recovery=False,
        ) is False


class TestScenarioAValidator:
    """三闸对面试四步产物为绿；越界预算可读拒绝。"""

    def test_interview_steps_pass_three_gates(self):
        specs = support.interview_specs()
        surface = support.interview_context().tool_surface
        validator = PlanValidator()
        assert validator.validate_shape(specs, max_depth=2) == []
        assert validator.validate_binding(specs, surface) == []
        assert validator.validate_budget(specs, plan_versions=1, budget=BUDGET) == []

    def test_over_budget_is_rejected_with_readable_reason(self):
        extra = SubGoalSpec.model_validate(
            {
                "index": 5,
                "description": "第五步",
                "capability": "create_reminder",
                "params": {"content": "多余步骤"},
                "criteria": {
                    "type": "action_succeeded",
                    "capability": "create_reminder",
                },
            }
        )
        specs = support.interview_specs() + [extra]
        budget = dict(BUDGET)
        budget["max_steps"] = 4
        reasons = PlanValidator.validate_budget(specs, plan_versions=1, budget=budget)
        assert reasons
        assert any("subgoal_count_exceeded" in reason for reason in reasons)
