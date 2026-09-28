"""PLAN-005 Step 7：失败判定树 / `on_failure` 矩阵 / 双层重试对齐 / G-RETRY 端到端。

覆盖 Task Detail §9.1 U5（矩阵在 `test_plan005_scheduler.py` 逐行断言）、§9.2 I4、I7、I11 与
§9.3 S2 / S3 / S10 的可判定部分。本模块的重点是**跨组件**的语义：`blocked` 四类处置、
退避数学调用点唯一、以及「重规划不重复世界副作用」（G-RETRY）。
"""

import pytest

from app.models.action import ACTION_STATUSES, GATE_REASONS
from app.models.plan import PLAN_STEP_OUTCOME_ACTION_STATUS, PLAN_STEP_OUTCOME_VALUES
from app.repositories import action_repository, goal_repository
from app.services.planning import executor_bridge as bridge_mod
from app.services.planning import scheduler as scheduler_mod
from app.services.planning.observer import PlanObserver
from app.services.planning.revision import PlanRevisionPolicy

from . import plan005_support as support
from .conftest import V25_NOW, V25_USER

BRIDGE = bridge_mod.PlanExecutorBridge(
    registry=None, session_resolver=lambda _user_id: None
)
POLICY = PlanRevisionPolicy()

WORLD_OP_KEY = "deferred_world_op"


class TestFailureJudgementTree:
    """§4.3.6 判定树：`blocked` 四类各有处置，逐分支可对照。"""

    @pytest.mark.parametrize(
        ("gate_reason", "status", "failure_kind", "step_status"),
        (
            ("permission_denied", "blocked", "denied", "failed"),
            ("invalid_params", "blocked", "invalid", "failed"),
            ("ambiguous_params", "blocked", "invalid", "failed"),
            ("capability_unavailable", "blocked", "unavailable", "in_progress"),
            ("pending_confirmation", "blocked", None, "in_progress"),
        ),
    )
    def test_blocked_branches(
        self, gate_reason, status, failure_kind, step_status
    ):
        record_status = "planned" if gate_reason == "pending_confirmation" else "cancelled"
        record = support.action_record(
            status=record_status, gate_reason=gate_reason, steps=[]
        )
        step = support.spec(1, tool_id=support.REMINDER_CREATE)
        outcome = bridge_mod._normalize(step, record, V25_NOW)
        assert (outcome.status, outcome.failure_kind) == (status, failure_kind)
        updated = BRIDGE.reconcile(outcome, step, max_attempts=2)
        assert updated.status == step_status, gate_reason

    def test_denied_is_never_retried(self):
        record = support.action_record(status="cancelled", gate_reason="permission_denied", steps=[])
        step = support.spec(1, attempt_count=0)
        updated = BRIDGE.reconcile(
            bridge_mod._normalize(step, record, V25_NOW), step, max_attempts=2
        )
        assert updated.status == "failed"
        assert updated.attempt_count == 0
        assert updated.last_attempt_at is None or updated.last_attempt_at == V25_NOW

    def test_pending_confirmation_keeps_the_step_waiting(self):
        record = support.action_record(status="planned", gate_reason="pending_confirmation", steps=[])
        step = support.spec(1)
        updated = BRIDGE.reconcile(
            bridge_mod._normalize(step, record, V25_NOW), step, max_attempts=2
        )
        assert updated.status == "in_progress"
        assert updated.failure_note is None

    def test_unavailable_waits_for_the_next_tick(self):
        record = support.action_record(
            status="cancelled", gate_reason="capability_unavailable", steps=[]
        )
        step = support.spec(1, tool_id=support.CHANNEL_SEND)
        outcome = bridge_mod._normalize(step, record, V25_NOW)
        updated = BRIDGE.reconcile(outcome, step, max_attempts=2)
        assert updated.status == "in_progress"
        assert updated.failure_note is None

    def test_persistently_off_surface_step_triggers_a_replan(self):
        """S7：`blocked_reason="off_surface"` 连续计数达阈 → 换工具重规划。"""
        step = support.spec(1, tool_id=support.CHANNEL_SEND, on_failure="replan")
        plan = support.plan([step.model_copy(update={"status": "in_progress"})])
        blocked = scheduler_mod.PlanScheduler.blocked_reason(
            plan, support.ctx(support.REMINDER_CREATE)
        )
        assert blocked == scheduler_mod.BLOCKED_OFF_SURFACE
        record = support.action_record(
            status="cancelled", gate_reason="capability_unavailable", steps=[]
        )
        outcome = bridge_mod._normalize(step, record, V25_NOW)
        assert (
            POLICY.should_replan(
                outcome, plan, _revision_ctx(off_surface_streak=2)
            )
            == "tool_persistently_unavailable"
        )
        assert POLICY.should_replan(outcome, plan, _revision_ctx()) is None

    def test_outcome_action_status_mapping_is_the_plan_002_freeze(self):
        assert PLAN_STEP_OUTCOME_ACTION_STATUS == {
            "succeeded": "succeeded",
            "failed": "failed",
            "timeout": "failed",
            "blocked": "cancelled",
            "skipped": None,
            "hold": "planned",
        }
        assert set(PLAN_STEP_OUTCOME_ACTION_STATUS) == set(PLAN_STEP_OUTCOME_VALUES)
        assert all(
            value is None or value in ACTION_STATUSES
            for value in PLAN_STEP_OUTCOME_ACTION_STATUS.values()
        )

    def test_no_new_action_status_or_gate_reason_values(self):
        assert ACTION_STATUSES == (
            "created",
            "planned",
            "executing",
            "succeeded",
            "failed",
            "cancelled",
        )
        assert GATE_REASONS == (
            "disabled",
            "ambiguous_params",
            "capability_unavailable",
            "duplicate",
            "quota_exceeded",
            "effect_already_satisfied",
            "target_not_found",
            "permission_denied",
            "invalid_params",
            "pending_confirmation",
        )
        assert set(bridge_mod.GATE_REASON_OUTCOMES) <= set(GATE_REASONS) | {"expired"}


def _revision_ctx(**overrides):
    """修订判据上下文（连续计数由调用方维护，纯函数只读）。"""
    from types import SimpleNamespace

    payload = {
        "step_max_attempts": 2,
        "off_surface_streak": 0,
        "undecidable_streak": 0,
        "insight_driven": False,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


class TestDoubleLayerRetryAlignment:
    """I4 / §4.3.5：退避数学只有一份（Action 层），Plan 层零退避、零等待。"""

    def test_planning_package_has_no_backoff_surface(self):
        from . import _plan_scan as scan

        offenders = {}
        for path in scan.planning_modules():
            if path.name not in _plan005_modules():
                continue
            hits = scan.code_violations(
                path, ("sleep", "backoff", "next_retry_at", "retry_delay")
            )
            if hits:
                offenders[path.name] = hits
        assert offenders == {}

    def test_backoff_math_lives_once_in_the_action_layer(self):
        from pathlib import Path

        from app.application import action_engine

        app_root = Path(action_engine.__file__).parents[1]
        math_files = sorted(
            path.relative_to(app_root).as_posix()
            for path in app_root.rglob("*.py")
            if "action_retry_backoff_seconds * (2 ** " in path.read_text(encoding="utf-8")
        )
        assert math_files == ["application/action_engine.py"]

    def test_reconcile_never_touches_next_retry_at(self):
        step = support.spec(1)
        outcome = bridge_mod.PlanStepOutcome(
            step_index=1, status="failed", at=V25_NOW, failure_kind="transient"
        )
        updated = BRIDGE.reconcile(outcome, step, max_attempts=2)
        assert set(updated.model_dump()) == set(step.model_dump())
        assert "next_retry_at" not in type(updated).model_fields

    def test_retryable_kind_stays_a_hold_until_the_action_layer_settles(self):
        record = support.action_record(
            status="executing", step_status="failed", failure_kind="transient", attempt=2
        )
        step = support.spec(1)
        outcome = bridge_mod._normalize(step, record, V25_NOW)
        assert outcome.status == "hold"
        assert BRIDGE.reconcile(outcome, step, max_attempts=2).attempt_count == 0


def _generated(index: int, description: str) -> dict:
    """LLM 提案里的一步（重规划会重新生成，保留步由引擎按 `index` 覆盖回来）。"""
    return {
        "index": index,
        "description": description,
        "capability": "create_reminder",
        "params": {"content": description},
        "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
    }


def _plan005_modules() -> tuple[str, ...]:
    return (
        "scheduler.py",
        "executor_bridge.py",
        "observer.py",
        "revision.py",
    )


@pytest.fixture
def planning_on(override_settings):
    """编排常开（总闸已删），只钉重规划预算与世界/观测面。"""
    override_settings(
        plan_revision_budget="3",
        observability_persist_enabled="false")


class TestGRetryNoDuplicateWorldEffects:
    """I7 / S10：重规划后已完成步骤不重做——`deferred_world_op` 计数不增加。"""

    @staticmethod
    def _world_op_count(user_id: str) -> int:
        count = 0
        for record in action_repository.list_records(user_id, limit=50):
            for step in record.steps or []:
                payload = (step.get("result") or {}).get("payload") or {}
                if payload.get(WORLD_OP_KEY):
                    count += 1
        return count

    @staticmethod
    def _executed_reminder(goal_id: str, user_id: str):
        return support.action_record(
            user_id=user_id,
            goal_id=goal_id,
            dedupe_key=f"plan:{goal_id}:1:1",
            steps=[
                {
                    "index": 1,
                    "capability": "reminder",
                    "action": "create",
                    "status": "succeeded",
                    "tool_id": support.REMINDER_CREATE,
                    "result": {
                        "status": "succeeded",
                        "effects": [{"kind": "world", "ref": "ev-1", "reversible": True}],
                        "observations": {"reminder_id": "ev-1"},
                        "payload": {WORLD_OP_KEY: {"op": "create_event", "title": "休息"}},
                    },
                }
            ],
        )

    @pytest.mark.asyncio
    async def test_replan_keeps_the_done_step_and_adds_no_world_op(
        self,
        db_session_factory,
        planning_on,
        make_goal,
        make_plan,
        stub_planning_llm,
    ):
        from app.core.settings import get_settings
        from app.services.planning import context as plan_context
        from app.services.planning import engine as plan_engine

        goal = make_goal(user_id=V25_USER, description="旅行计划")
        step_one = {
            "index": 1,
            "description": "订机票",
            "capability": "create_reminder",
            "params": {"content": "订机票"},
            "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
            "tool_id": support.REMINDER_CREATE,
            "observation_keys": ["reminder_id"],
            "status": "done",
        }
        step_two = {
            "index": 2,
            "description": "订酒店",
            "capability": "create_reminder",
            "params": {"content": "订酒店"},
            "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
            "depends_on": [1],
        }
        plan = make_plan(goal.id, [step_one, step_two])
        action_repository.save_record(self._executed_reminder(goal.id, V25_USER))
        before = self._world_op_count(V25_USER)
        assert before == 1

        stub_planning_llm(sub_goals=[_generated(1, "订机票"), dict(step_two)])
        ctx = plan_context.PlanContext(
            goal=goal,
            tool_surface=plan_context.ToolSurface(
                run_kind="autonomous_tick", tool_ids=(support.REMINDER_CREATE,)
            ),
            budget=plan_context.plan_budget(get_settings()),
        )
        outcome = await plan_engine.PlanningEngine().revise(
            plan, ctx, reason="step_attempt_exhausted"
        )
        assert outcome.status == plan_engine.PLAN_STATUS_VALIDATED
        new_plan = goal_repository.get_latest_plan(goal.id)
        assert new_plan.version == 2
        kept = new_plan.sub_goals[0]
        assert kept.index == 1 and kept.status == "done"
        assert kept.criteria == plan.sub_goals[0].criteria
        assert kept.tool_id == support.REMINDER_CREATE
        assert goal_repository.get_plan(plan.id).status == "superseded"

        ready = [spec.index for spec in scheduler_mod.PlanScheduler.ready_steps(new_plan)]
        assert ready == [2], "保留步不得再次进入就绪集（不重做、不重复副作用）"
        assert self._world_op_count(V25_USER) == before == 1

    @pytest.mark.asyncio
    async def test_world_effect_is_not_duplicated_for_the_kept_step(
        self,
        db_session_factory,
        planning_on,
        make_goal,
        make_plan,
        stub_planning_llm,
    ):
        """S10 的对照：若保留步被重做（人为制造），计数才会增加——证明计数口径可判。"""
        from app.core.settings import get_settings
        from app.services.planning import context as plan_context
        from app.services.planning import engine as plan_engine

        goal = make_goal(user_id=V25_USER, description="对照目标")
        plan = make_plan(
            goal.id,
            [
                {
                    "index": 1,
                    "description": "已完成的提醒",
                    "capability": "create_reminder",
                    "params": {"content": "已完成的提醒"},
                    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
                    "tool_id": support.REMINDER_CREATE,
                    "status": "done",
                }
            ],
        )
        action_repository.save_record(self._executed_reminder(goal.id, V25_USER))
        assert self._world_op_count(V25_USER) == 1
        stub_planning_llm(
            sub_goals=[
                {
                    "index": 1,
                    "description": "重做提醒",
                    "capability": "create_reminder",
                    "params": {"content": "重做提醒"},
                    "criteria": {"type": "action_succeeded", "capability": "create_reminder"},
                }
            ]
        )
        ctx = plan_context.PlanContext(
            goal=goal,
            tool_surface=plan_context.ToolSurface(run_kind="autonomous_tick", tool_ids=()),
            budget=plan_context.plan_budget(get_settings()),
        )
        await plan_engine.PlanningEngine().revise(
            plan, ctx, reason="step_attempt_exhausted"
        )
        new_plan = goal_repository.get_latest_plan(goal.id)
        assert new_plan.sub_goals[0].status == "done"
        assert new_plan.sub_goals[0].description == "已完成的提醒"
        assert self._world_op_count(V25_USER) == 1


class TestObservationOnActionFailure:
    """S2：单步失败但未达上限 → 留在 `in_progress` 等 Action 层退避。"""

    def test_transient_failure_below_the_limit_is_retrying(
        self, db_session_factory, planning_on, make_goal, make_plan, goal_facts
    ):
        goal = make_goal(user_id=V25_USER, description="瞬时失败")
        make_plan(goal.id)
        detail = PlanObserver().observe_user_goals(
            V25_USER, goal_facts(), now=V25_NOW
        )
        assert detail["results"][0]["outcome"] == "hold"
        assert goal_repository.get_latest_plan(goal.id).sub_goals[0].attempt_count == 1
        assert goal_repository.get_goal(goal.id).status == "active"
