"""PLAN-012 场景集 C：Tool 调用流程（PlanStep → Intent → 归一 → reconcile）。"""

from app.models.action import ActionIntent
from app.models.plan import PLAN_STEP_DEDUPE_KEY_TEMPLATE, PlanStepOutcome
from app.models.tool import TOOL_FAILURE_KIND_VALUES
from app.services.planning.executor_bridge import PlanExecutorBridge

from . import plan005_support as support005
from . import plan012_support as support

BRIDGE = PlanExecutorBridge(settings=None)


class TestScenarioCToolInvocationChain:
    """S3：步骤执行链的归一与幂等键可复现；结果契约落在既有值集内。"""

    def test_to_intent_produces_deterministic_dedupe_key(self):
        plan = support005.plan(
            [support005.spec(1, tool_id=support.MEMORY_SAVE, capability="remember_fact")]
        )
        step = plan.sub_goals[0]
        ctx = support005.ctx(support.MEMORY_SAVE)
        intent = BRIDGE.to_intent(support005.goal(), plan, step, ctx)
        assert isinstance(intent, ActionIntent)
        assert intent.action_type
        expected = PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(
            goal_id=support005.GOAL_ID, version=1, index=step.index
        )
        assert intent.dedupe_key == expected
        again = BRIDGE.to_intent(support005.goal(), plan, step, ctx)
        assert again.dedupe_key == intent.dedupe_key

    def test_outcome_failure_kinds_stay_inside_the_frozen_set(self):
        for kind in (
            "transient",
            "timeout",
            "permanent",
            "unavailable",
            "denied",
            "invalid",
        ):
            outcome = PlanStepOutcome(
                step_index=1, status="blocked", at=support.NOW, failure_kind=kind
            )
            assert outcome.failure_kind in TOOL_FAILURE_KIND_VALUES

    def test_reconcile_updates_a_memory_copy(self):
        step = support005.spec(1, status="pending")
        outcome = PlanStepOutcome(
            step_index=1,
            status="succeeded",
            at=support.NOW,
            tool_id=support.REMINDER_CREATE,
            action_id="act-1",
        )
        updated = BRIDGE.reconcile(outcome, step, max_attempts=2)
        assert updated.attempt_count == 1
        assert step.status == "pending", "reconcile 不得原地改写调用方传入对象"

    def test_action_record_shapes_support_three_account_projection(self):
        record = support005.action_record(status="succeeded")
        assert record.steps[0]["result"]["status"] == "succeeded"
        assert record.steps[0]["tool_id"] == support005.REMINDER_CREATE
        assert record.dedupe_key is not None or record.dedupe_key == ""
