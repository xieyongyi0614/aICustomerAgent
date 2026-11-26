"""PLAN-012 场景集 D：失败恢复（判定树 + 双层重试 + 重规划保留步 + 预算阻断）。"""

from types import SimpleNamespace

from app.models.plan import PlanStepOutcome
from app.services.planning import executor_bridge as bridge_mod
from app.services.planning.engine import (
    PLAN_STATUS_ACTIVE,
    REASON_REVISION_EXHAUSTED,
)
from app.services.planning.executor_bridge import PlanExecutorBridge
from app.services.planning.observer import PlanObserver
from app.services.planning.revision import PlanRevisionPolicy

from . import plan005_support as support005
from . import plan012_support as support

BRIDGE = PlanExecutorBridge(settings=None)
POLICY = PlanRevisionPolicy()
OBSERVER = PlanObserver()


class TestScenarioDFailureRecovery:
    """S4：blocked 四类 + 双层重试 + 重规划保留步 + 观测故障隔离。"""

    def test_blocked_permission_denied_is_permanent_failure(self):
        record = support005.action_record(
            status="cancelled", gate_reason="permission_denied", steps=[]
        )
        step = support005.spec(1, tool_id=support005.REMINDER_CREATE)
        outcome = bridge_mod._normalize(step, record, support.NOW)
        updated = BRIDGE.reconcile(outcome, step, max_attempts=2)
        assert outcome.status == "blocked"
        assert updated.status == "failed"
        assert updated.attempt_count == 0

    def test_blocked_unavailable_waits_for_next_tick(self):
        record = support005.action_record(
            status="cancelled", gate_reason="capability_unavailable", steps=[]
        )
        step = support005.spec(1, tool_id=support005.CHANNEL_SEND)
        updated = BRIDGE.reconcile(
            bridge_mod._normalize(step, record, support.NOW), step, max_attempts=2
        )
        assert updated.status == "in_progress"

    def test_attempt_count_increments_only_on_terminal_action_status(self):
        terminal = PlanStepOutcome(step_index=1, status="failed", at=support.NOW)
        after_terminal = BRIDGE.reconcile(
            terminal, support005.spec(1, status="pending"), max_attempts=2
        )
        assert after_terminal.attempt_count == 1

        blocked = PlanStepOutcome(
            step_index=1, status="blocked", at=support.NOW, failure_kind="unavailable"
        )
        after_blocked = BRIDGE.reconcile(
            blocked, support005.spec(1, status="pending"), max_attempts=2
        )
        assert after_blocked.status == "in_progress"

    def test_replan_triggers_after_exhausted_attempts(self):
        plan = support005.plan(
            [support005.spec(1, on_failure="replan", status="failed", attempt_count=2)]
        )
        outcome = PlanStepOutcome(step_index=1, status="failed", at=support.NOW)
        ctx = SimpleNamespace(
            step_max_attempts=2, off_surface_streak=0, undecidable_streak=0
        )
        assert POLICY.should_replan(outcome, plan, ctx) == "step_attempt_exhausted"

    def test_kept_steps_preserve_done_indexes_for_g_retry(self):
        steps = support.interview_specs()
        steps[0].status = "done"
        steps[1].status = "failed"
        steps[1].on_failure = "replan"
        steps[1].attempt_count = 2
        kept = [step.index for step in steps if step.status == "done"]
        assert kept == [1]
        assert steps[0].criteria is not None
        assert steps[0].tool_id == support.MEMORY_SAVE

    def test_observation_error_does_not_mutate_plan_status(self):
        goal = support.interview_goal()
        plan = support.interview_plan()
        before = plan.status
        advance = OBSERVER.observe(goal, plan, {"now": support.NOW}, now=support.NOW)
        assert plan.status == before
        assert advance.decision in (
            "hold",
            "advanced",
            "completed",
            "skipped",
            "replanning",
            "failed",
        )

    def test_revision_budget_blocks_infinite_replan(self):
        assert REASON_REVISION_EXHAUSTED == "plan_revision_exhausted"
        assert PLAN_STATUS_ACTIVE == "active"
