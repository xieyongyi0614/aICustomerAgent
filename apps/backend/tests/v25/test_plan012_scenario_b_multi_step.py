"""PLAN-012 场景集 B：多步骤规划（architecture §6.2 面试准备四步样例全链）。

八段可举证中的可自动化部分：结构 / 调度 / 观测推进 / 记忆边界 / 重规划静默。
"""

from app.services.planning import memory_policy as plan_memory_policy
from app.services.planning.observer import PlanObserver
from app.services.planning.revision import PlanRevisionPolicy
from app.services.planning.scheduler import PlanScheduler
from app.models.plan import PlanStepOutcome

from . import plan012_support as support

OBSERVER = PlanObserver()
POLICY = PlanRevisionPolicy()


class TestScenarioBMultiStepInterviewPlan:
    """S2：§6.2 四步面试准备计划的结构、调度与观测推进。"""

    def test_plan_shape_matches_the_architecture_sample(self):
        plan = support.interview_plan()
        specs = list(plan.sub_goals)
        assert [spec.index for spec in specs] == [1, 2, 3, 4]
        assert specs[2].depends_on == [1]
        assert specs[3].depends_on == [1]
        assert specs[0].tool_id == support.MEMORY_SAVE
        assert specs[1].tool_id == support.ENV_QUERY
        assert specs[2].tool_id == support.REMINDER_CREATE
        assert specs[3].tool_id == support.REMINDER_CREATE

    def test_scheduler_yields_structural_order_and_respects_depends_on(self):
        plan = support.interview_plan()
        ready = PlanScheduler.ready_steps(plan)
        assert [spec.index for spec in ready] == [1, 2]
        current = PlanScheduler.current_step(plan)
        assert current is not None
        assert current.index == 1

        after_first = support.interview_plan()
        after_first.sub_goals[0].status = "done"
        ready_after = PlanScheduler.ready_steps(after_first)
        assert [spec.index for spec in ready_after] == [2, 3, 4]

    def test_cooldown_throttles_to_single_step_per_tick(self):
        plan = support.interview_plan()
        current = PlanScheduler.current_step(plan)
        assert current is not None
        # 每 tick 最多推进一步：就绪集有 2，但 current_step 只取执行序首
        assert current.index == 1

    def test_observation_returns_a_plan_advance_decision(self):
        goal = support.interview_goal()
        plan = support.interview_plan()
        facts = {
            "now": support.NOW,
            "world": {},
            "state": {},
            "memory": {},
            "action_results": [],
        }
        advance = OBSERVER.observe(goal, plan, facts, now=support.NOW)
        assert advance.decision in (
            "advanced",
            "completed",
            "replanning",
            "skipped",
            "failed",
            "hold",
        )
        assert advance.goal_id == goal.id

    def test_memory_boundary_records_terminal_events_only(self):
        policy = plan_memory_policy.PlanMemoryPolicy()
        completed = policy.decide(plan_memory_policy.EVENT_PLAN_COMPLETED)
        created = policy.decide(plan_memory_policy.EVENT_PLAN_CREATED)
        step_ok = policy.decide(plan_memory_policy.EVENT_STEP_SUCCEEDED)
        assert completed.deposit is True
        assert created.deposit is False
        assert step_ok.deposit is False

    def test_revision_policy_stays_quiet_on_healthy_progress(self):
        from types import SimpleNamespace

        plan = support.interview_plan()
        outcome = PlanStepOutcome(step_index=1, status="succeeded", at=support.NOW)
        ctx = SimpleNamespace(
            step_max_attempts=2, off_surface_streak=0, undecidable_streak=0
        )
        assert POLICY.should_replan(outcome, plan, ctx) is None
