"""PLAN-005 Step 6：重规划裁决（四条判据 / 保留步 / 修订预算终止 / 策略映射）。

覆盖 Task Detail §9.1 U14~U18；G-RETRY 的「不重复世界副作用」端到端举证在
`test_plan005_failure_tree.py`（需要台账计数）。
"""

from types import SimpleNamespace

import pytest

from app.core.settings import get_settings
from app.models.goal import ON_FAILURE_MODES, RETRY_MODES
from app.models.plan import (
    PLAN_REVISION_REASONS,
    PLAN_STEP_ATTEMPT_INCREMENT_STATUSES,
    PlanStepOutcome,
    RetryPolicy,
)
from app.services.planning import revision as revision_mod
from app.services.planning.revision import PlanRevisionPolicy

from . import plan005_support as support
from .conftest import V25_NOW, V25_USER

POLICY = PlanRevisionPolicy()

REVISION_REASONS = revision_mod.REVISION_REASONS

FAILED_OUTCOME = PlanStepOutcome(step_index=1, status="failed", at=V25_NOW)
BLOCKED_OUTCOME = PlanStepOutcome(
    step_index=1, status="blocked", at=V25_NOW, failure_kind="denied"
)


def _ctx(**overrides):
    """修订判据上下文：连续计数与阈值由调用方注入（纯函数零 IO 的必要条件）。"""
    payload = {
        "step_max_attempts": 2,
        "off_surface_streak": 0,
        "undecidable_streak": 0,
        "insight_driven": False,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class TestShouldReplan:
    """U14：四个理由码各一例；不满足即 `None`（纯判定，零副作用）。"""

    def test_exhausted_attempts_with_replan_mode(self):
        plan = support.plan(
            [support.spec(1, on_failure="replan", status="failed", attempt_count=2)]
        )
        assert (
            POLICY.should_replan(FAILED_OUTCOME, plan, _ctx())
            == revision_mod.REASON_STEP_ATTEMPT_EXHAUSTED
        )

    def test_below_the_limit_does_not_replan(self):
        plan = support.plan(
            [support.spec(1, on_failure="replan", status="failed", attempt_count=1)]
        )
        assert POLICY.should_replan(FAILED_OUTCOME, plan, _ctx()) is None

    def test_non_retryable_kind_replans_without_burning_attempts(self):
        plan = support.plan(
            [support.spec(1, on_failure="replan", status="failed", attempt_count=0)]
        )
        outcome = PlanStepOutcome(
            step_index=1, status="failed", at=V25_NOW, failure_kind="permanent"
        )
        assert (
            POLICY.should_replan(outcome, plan, _ctx())
            == revision_mod.REASON_STEP_ATTEMPT_EXHAUSTED
        )

    def test_denied_blocked_step_replans(self):
        plan = support.plan(
            [support.spec(1, on_failure="replan", status="failed", attempt_count=0)]
        )
        assert (
            POLICY.should_replan(BLOCKED_OUTCOME, plan, _ctx())
            == revision_mod.REASON_STEP_ATTEMPT_EXHAUSTED
        )

    def test_replan_mode_is_required(self):
        for mode in ("abort", "skip", "continue"):
            plan = support.plan(
                [support.spec(1, on_failure=mode, status="failed", attempt_count=9)]
            )
            assert POLICY.should_replan(FAILED_OUTCOME, plan, _ctx()) is None, mode

    def test_persistently_unavailable_tool(self):
        plan = support.plan([support.spec(1, tool_id=support.CHANNEL_SEND)])
        assert (
            POLICY.should_replan(FAILED_OUTCOME, plan, _ctx(off_surface_streak=2))
            == revision_mod.REASON_TOOL_PERSISTENTLY_UNAVAILABLE
        )

    def test_off_surface_streak_below_the_threshold_is_none(self):
        plan = support.plan([support.spec(1, tool_id=support.CHANNEL_SEND)])
        assert POLICY.should_replan(FAILED_OUTCOME, plan, _ctx(off_surface_streak=1)) is None

    def test_undecidable_criteria_streak(self):
        plan = support.plan([support.spec(1)])
        assert (
            POLICY.should_replan(FAILED_OUTCOME, plan, _ctx(undecidable_streak=2))
            == revision_mod.REASON_CRITERIA_UNDECIDABLE
        )

    def test_insight_driven_entrance(self):
        plan = support.plan([support.spec(1)])
        assert (
            POLICY.should_replan(FAILED_OUTCOME, plan, _ctx(insight_driven=True))
            == revision_mod.REASON_INSIGHT_DRIVEN
        )

    def test_judgement_order_is_the_table_order(self):
        plan = support.plan(
            [support.spec(1, on_failure="replan", status="failed", attempt_count=2)]
        )
        assert (
            POLICY.should_replan(
                FAILED_OUTCOME, plan, _ctx(off_surface_streak=9, insight_driven=True)
            )
            == revision_mod.REASON_STEP_ATTEMPT_EXHAUSTED
        )

    def test_reason_codes_match_the_plan_002_freeze(self):
        assert REVISION_REASONS == PLAN_REVISION_REASONS
        assert revision_mod.REVISION_REASONS == (
            "step_attempt_exhausted",
            "tool_persistently_unavailable",
            "criteria_undecidable",
            "insight_driven",
        )

    def test_missing_step_in_plan_degrades_to_no_replan(self):
        """缺步不算业务失败：判定返回 `None`，由调用方的落库/断言负责。"""
        plan = support.plan([support.spec(2)])
        assert POLICY.should_replan(FAILED_OUTCOME, plan, _ctx()) is None


class TestKeptSteps:
    """U15：保留已完成步骤（不重做、不重复副作用），`kept_steps` 正确。"""

    @staticmethod
    def _plan():
        return support.plan(
            [
                support.spec(1, status="done", criteria={"type": "action_succeeded", "capability": "create_reminder"}),
                support.spec(2, status="failed", tool_id=support.REMINDER_CREATE),
                support.spec(3, depends_on=[2]),
            ]
        )

    def test_kept_steps_are_the_done_ones(self):
        assert PlanRevisionPolicy.kept_steps(self._plan()) == [1]
        assert PlanRevisionPolicy.dropped_steps(self._plan()) == [2, 3]

    def test_kept_steps_are_carried_into_the_explain_payload(self):
        payload = POLICY.explain(self._plan(), revision_mod.REASON_STEP_ATTEMPT_EXHAUSTED)
        assert payload["kept_steps"] == [1]
        assert payload["dropped_steps"] == [2, 3]
        assert payload["from_version"] == 1
        assert payload["to_version"] == 2
        assert payload["failed_steps"] == [
            {"index": 2, "attempt_count": 0, "failure_note": None}
        ]
        assert "保留已完成步骤 [1]" in payload["narrative"]

    def test_kept_steps_keep_index_and_criteria_when_merged(self):
        """与 PLAN-003 的合并函数同源：保留步在新版本里 `index` / 判据 / 工具不变。"""
        from app.services.planning.engine import _merge_kept_steps

        plan = self._plan()
        kept = [plan.sub_goals[0]]
        regenerated = [
            support.spec(1, description="重做步骤1", params={"content": "新"}),
            support.spec(2),
        ]
        merged = _merge_kept_steps(regenerated, kept)
        assert [spec.index for spec in merged] == [1, 2]
        assert merged[0] is kept[0]
        assert merged[0].criteria == kept[0].criteria
        assert merged[0].status == "done"


class TestRetryPolicyMapping:
    """U18：三值映射正确；`RetryPolicy` 不含退避字段（退避只有一份，在 Action 层）。"""

    def test_none_mode(self):
        policy = PlanRevisionPolicy.policy_for(support.spec(1, retry_policy="none"))
        assert (policy.mode, policy.max_attempts) == ("none", 0)
        assert policy.is_bounded is True

    def test_once_mode_default(self):
        policy = PlanRevisionPolicy.policy_for(support.spec(1))
        assert (policy.mode, policy.max_attempts) == ("once", 1)
        assert policy.is_bounded is True

    def test_until_budget_takes_the_settings_bound(self):
        policy = PlanRevisionPolicy.policy_for(
            support.spec(1, retry_policy="until_budget"), max_attempts=4
        )
        assert (policy.mode, policy.max_attempts) == ("until_budget", 4)
        assert policy.is_bounded is False

    def test_until_budget_default_mirrors_the_settings_default(self):
        policy = PlanRevisionPolicy.policy_for(support.spec(1, retry_policy="until_budget"))
        assert policy.max_attempts == get_settings().v25_plan_step_max_attempts == 2

    def test_retry_policy_has_no_backoff_field(self):
        assert tuple(RetryPolicy.model_fields) == ("mode", "max_attempts")
        assert revision_mod.RETRY_POLICY_ATTEMPTS == {"none": 0, "once": 1}

    def test_retry_modes_and_on_failure_modes_are_unchanged(self):
        assert RETRY_MODES == ("none", "once", "until_budget")
        assert ON_FAILURE_MODES == ("abort", "skip", "replan", "continue")


class TestRevisionBudget:
    """U16：达修订预算即终止（不再产生新版本，计划 `rejected` + 目标 `failed`）。"""

    def test_budget_is_not_exhausted_below_the_limit(self):
        plan = support.plan([support.spec(1)], version=2)
        assert POLICY.budget_exhausted(plan, revision_budget=3) is False

    def test_budget_is_exhausted_at_the_limit(self):
        plan = support.plan([support.spec(1)], version=3)
        assert POLICY.budget_exhausted(plan, revision_budget=3) is True
        assert PlanRevisionPolicy.budget_exhausted(
            support.plan([support.spec(1)], version=4), revision_budget=3
        )

    @pytest.mark.asyncio
    async def test_engine_terminates_without_producing_a_new_version(
        self, db_session_factory, override_settings, make_goal, make_plan
    ):
        """终止路径端到端：策略判「预算耗尽」→ 既有 `PlanningEngine.revise` 落终态。"""
        from app.repositories import goal_repository
        from app.services.planning import context as plan_context
        from app.services.planning import engine as plan_engine
        override_settings(
            v2_autonomy_advanced_enabled="true",
            v25_planning_enabled="true",
            v25_plan_revision_budget="1",
            world_enabled="false",
            observability_persist_enabled="false",
        )
        goal = make_goal(user_id=V25_USER, description="预算耗尽")
        plan = make_plan(goal.id, version=1)
        assert POLICY.budget_exhausted(plan, revision_budget=1) is True
        ctx = plan_context.PlanContext(
            goal=goal,
            tool_surface=plan_context.ToolSurface(
                run_kind="autonomous_tick", tool_ids=()
            ),
            budget=plan_context.plan_budget(get_settings()),
        )
        outcome = await plan_engine.PlanningEngine().revise(
            plan, ctx, reason=revision_mod.REASON_STEP_ATTEMPT_EXHAUSTED
        )
        assert outcome.status == plan_engine.PLAN_STATUS_REJECTED
        assert outcome.rejection_reason == plan_engine.REASON_REVISION_EXHAUSTED
        assert len(goal_repository.list_plans(goal.id)) == 1
        reloaded = goal_repository.get_goal(goal.id)
        assert (reloaded.status, reloaded.failure_reason) == ("failed", "plan_exhausted")

    def test_explain_payload_is_json_serialisable_and_deterministic(self):
        import json

        plan = support.plan([support.spec(1, status="done"), support.spec(2)])
        payload = POLICY.explain(plan, revision_mod.REASON_CRITERIA_UNDECIDABLE)
        assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
        assert payload == POLICY.explain(plan, revision_mod.REASON_CRITERIA_UNDECIDABLE)


class TestFailurePropagationIsNotDuplicated:
    """纪律：本模块只出理由码，不执行动作、不入队、不落库（D14）。"""

    def test_policy_source_has_no_repository_or_enqueue_calls(self):
        from pathlib import Path

        from . import _plan_scan as scan

        path = Path(revision_mod.__file__)
        called = {node.func.id for node in scan.call_nodes(path) if hasattr(node.func, "id")}
        assert "enqueue_planning" not in called
        assert "get_settings" not in called
        assert not [
            module
            for module in scan.imported_modules(path)
            if module.startswith("app.repositories")
            or module.startswith("app.application")
        ]

    def test_attempt_increment_statuses_are_the_plan_002_freeze(self):
        assert PLAN_STEP_ATTEMPT_INCREMENT_STATUSES == ("succeeded", "failed")

    def test_no_sleep_or_backoff_surface(self):
        from pathlib import Path

        from . import _plan_scan as scan

        path = Path(revision_mod.__file__)
        assert scan.code_violations(
            path, ("sleep", "next_retry_at", "timedelta", "backoff")
        ) == []
