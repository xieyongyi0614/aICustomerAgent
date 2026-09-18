"""PLAN-005 Step 2 / Step 3：执行桥（翻译 / 防御性断言 / 结果归一 / 回填）。

覆盖 Task Detail §9.1 U6~U10 与 §9.2 I1、I2、I11 的可判定部分；静态红线（G-EXEC / 零退避）
见 `test_plan005_static_scan.py`，失败判定树与退避对齐见 `test_plan005_failure_tree.py`。
"""

import pytest

from app.application.agent_runtime.models import RUN_KIND_AUTONOMOUS_TICK
from app.models.action import ACTION_TYPES
from app.models.plan import (
    PLAN_STEP_ACTION_CONFIDENCE,
    PLAN_STEP_DEDUPE_KEY_TEMPLATE,
    PLAN_STEP_OUTCOME_VALUES,
)
from app.models.tool import TOOL_FAILURE_KINDS
from app.services.planning import executor_bridge as bridge_mod
from app.services.planning.executor_bridge import PlanBridgeDefect, PlanExecutorBridge
from app.services.tool.registry import ToolRegistry, register_builtin_tools

from . import plan005_support as support

NOW = support.NOW
BRIDGE = PlanExecutorBridge(settings=None)


class _Recorder:
    """`run_action_planning` 替身：记录调用并返回预置记录（零 DB、零工具执行）。"""

    def __init__(self, record=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._record = record
        self._error = error

    async def __call__(self, user_id, intent, session_id=None, goal_id=None, source=None):
        self.calls.append(
            {
                "user_id": user_id,
                "intent": intent,
                "session_id": session_id,
                "goal_id": goal_id,
                "source": source,
            }
        )
        if self._error is not None:
            raise self._error
        return self._record


def _bridge(**kwargs) -> PlanExecutorBridge:
    kwargs.setdefault("registry", _registry())
    kwargs.setdefault("session_resolver", lambda _user_id: None)
    return PlanExecutorBridge(**kwargs)


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


def _ctx(*tool_ids: str, now=NOW):
    return support.ctx(*tool_ids, now=now)


def _ready_plan(**overrides):
    return support.plan([support.spec(1, tool_id=support.REMINDER_CREATE, **overrides)])


class TestToIntent:
    """U6 / U7 / D4：确定性幂等键、能力反查、禁空 `action_type`。"""

    def test_dedupe_key_is_the_step_level_template(self):
        plan = _ready_plan()
        intent = BRIDGE.to_intent(support.goal(), plan, plan.sub_goals[0], _ctx())
        assert intent.dedupe_key == PLAN_STEP_DEDUPE_KEY_TEMPLATE.format(
            goal_id=support.GOAL_ID, version=1, index=1
        )
        assert intent.dedupe_key == "plan:plan5-goal:1:1"

    def test_dedupe_key_is_reproducible_and_version_sensitive(self):
        step = _ready_plan().sub_goals[0]
        first = BRIDGE.to_intent(support.goal(), _ready_plan(), step, _ctx())
        second = BRIDGE.to_intent(support.goal(), _ready_plan(), step, _ctx())
        other_version = BRIDGE.to_intent(
            support.goal(), support.plan([step], version=2), step, _ctx()
        )
        assert first.dedupe_key == second.dedupe_key
        assert first.dedupe_key != other_version.dedupe_key

    def test_action_type_is_the_validated_capability(self):
        plan = _ready_plan()
        intent = BRIDGE.to_intent(support.goal(), plan, plan.sub_goals[0], _ctx())
        assert intent.action_type in ACTION_TYPES
        assert intent.action_type == "create_reminder"
        assert intent.action_type != ""
        assert intent.confidence == PLAN_STEP_ACTION_CONFIDENCE == "confident"

    def test_capability_role_name_is_reverse_mapped(self):
        step = support.spec(1, capability="notification")
        intent = BRIDGE.to_intent(support.goal(), support.plan([step]), step, _ctx())
        assert intent.action_type == "send_notification"

    def test_ambiguous_role_name_is_refused(self):
        """`reminder` 同时对应 create / cancel：反查不唯一即抛实现缺陷，绝不猜。"""
        step = support.spec(1, capability="reminder")
        with pytest.raises(PlanBridgeDefect):
            BRIDGE.to_intent(support.goal(), support.plan([step]), step, _ctx())

    def test_unmappable_capability_raises_a_defect(self):
        step = support.spec(1, capability="not_a_capability")
        with pytest.raises(PlanBridgeDefect):
            BRIDGE.to_intent(support.goal(), support.plan([step]), step, _ctx())

    def test_params_are_passed_through_without_type_mangling(self):
        """与 §6.4 Step ③ 的核对项：参数不做 `normalize_core_params` 变换（原值透传）。"""
        step = support.spec(
            1,
            params={"content": "  提醒  内容 ", "count": 3, "optional": None},
        )
        intent = BRIDGE.to_intent(support.goal(), support.plan([step]), step, _ctx())
        assert intent.params == {"content": "  提醒  内容 ", "count": 3, "optional": None}

    def test_normalized_digest_lands_in_the_audit_evidence(self):
        step = support.spec(1, params={"content": " 提 醒 ", "count": 3, "none": None})
        intent = BRIDGE.to_intent(support.goal(), support.plan([step]), step, _ctx())
        assert '"count": "3"' in intent.evidence
        assert "none" not in intent.evidence
        assert intent.evidence.startswith("计划步骤 1：")

    def test_evidence_is_bounded(self):
        step = support.spec(1, params={"content": "长" * 400})
        intent = BRIDGE.to_intent(support.goal(), support.plan([step]), step, _ctx())
        assert len(intent.evidence) <= bridge_mod.EVIDENCE_DIGEST_BUDGET


class TestExecuteStep:
    """Step 3：唯一执行入口 + A1 / A2 防御性断言。"""

    @pytest.mark.asyncio
    async def test_delegates_to_run_action_planning_with_autonomy_source(self):
        runner = _Recorder(support.action_record())
        plan = _ready_plan()
        bridge = _bridge(runner=runner)
        outcome = await bridge.execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx(support.REMINDER_CREATE)
        )
        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call["user_id"] == support.USER_ID
        assert call["goal_id"] == support.GOAL_ID
        assert call["source"] == "autonomy"
        assert call["intent"].dedupe_key == "plan:plan5-goal:1:1"
        assert outcome.status == "succeeded"
        assert outcome.action_id == "action-1"

    @pytest.mark.asyncio
    async def test_a1_readiness_recheck_skips_without_executing(self):
        runner = _Recorder(support.action_record())
        plan = support.plan(
            [
                support.spec(1),
                support.spec(2, depends_on=[1], tool_id=support.REMINDER_CREATE),
            ]
        )
        outcome = await _bridge(runner=runner).execute_step(
            support.goal(), plan, plan.sub_goals[1], _ctx(support.REMINDER_CREATE)
        )
        assert outcome.status == "skipped"
        assert outcome.action_id is None
        assert runner.calls == []

    @pytest.mark.asyncio
    async def test_a1_skips_a_composite_parent(self):
        runner = _Recorder(support.action_record())
        plan = support.plan(
            [
                support.spec(1, kind="composite"),
                support.spec(2, parent_index=1, tool_id=support.REMINDER_CREATE),
            ]
        )
        outcome = await _bridge(runner=runner).execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx(support.REMINDER_CREATE)
        )
        assert outcome.status == "skipped"
        assert runner.calls == []

    @pytest.mark.asyncio
    async def test_a2_surface_recheck_blocks_without_executing(self):
        runner = _Recorder(support.action_record())
        plan = support.plan(
            [
                support.spec(
                    1,
                    capability="query_search",
                    tool_id="builtin.search.query",
                    params={"query": "天气"},
                )
            ]
        )
        outcome = await _bridge(runner=runner).execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx()
        )
        assert outcome.status == "blocked"
        assert outcome.failure_kind == "unavailable"
        assert outcome.tool_id == "builtin.search.query"
        assert runner.calls == []

    @pytest.mark.asyncio
    async def test_a2_blocks_a_tool_that_left_the_surface_at_late_night(self):
        """规划到执行之间跨时段：同一工具在 late_night 被面剔除（防御性断言的价值所在）。"""
        runner = _Recorder(support.action_record())
        plan = support.plan(
            [
                support.spec(
                    1,
                    capability="send_notification",
                    tool_id=support.CHANNEL_SEND,
                    params={"content": "该睡了"},
                )
            ]
        )
        bridge = _bridge(runner=runner)
        noon = await bridge.execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx(now=NOW)
        )
        night = await bridge.execute_step(
            support.goal(),
            plan,
            plan.sub_goals[0],
            _ctx(now=NOW.replace(hour=2)),
        )
        assert night.status == "blocked"
        assert night.failure_kind == "unavailable"
        assert runner.calls == [], f"面复核未拦下：{noon.status}"

    @pytest.mark.asyncio
    async def test_no_tool_id_step_skips_the_surface_assertion(self):
        """绑定子闸 off 的步骤（无 `tool_id`）不做面判定：工具选择属执行期 `ToolSelector`。"""
        runner = _Recorder(support.action_record())
        plan = support.plan([support.spec(1)])
        outcome = await _bridge(runner=runner).execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx()
        )
        assert outcome.status == "succeeded"
        assert len(runner.calls) == 1

    @pytest.mark.asyncio
    async def test_execution_exception_is_absorbed_as_permanent_failure(self):
        runner = _Recorder(error=RuntimeError("boom"))
        plan = _ready_plan()
        outcome = await _bridge(runner=runner).execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx(support.REMINDER_CREATE)
        )
        assert outcome.status == "failed"
        assert outcome.failure_kind == "permanent"

    @pytest.mark.asyncio
    async def test_action_disabled_yields_hold(self):
        runner = _Recorder(None)
        plan = _ready_plan()
        outcome = await _bridge(runner=runner).execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx(support.REMINDER_CREATE)
        )
        assert outcome.status == "hold"
        assert outcome.action_id is None


class TestOutcomeNormalisation:
    """U9 / U10：`ToolResult → PlanStepOutcome` 归一 + 白名单裁剪。"""

    @staticmethod
    def _normalize(record, *, observation_keys=(), **spec_overrides):
        step = support.spec(
            1, tool_id=support.REMINDER_CREATE, observation_keys=observation_keys, **spec_overrides
        )
        return bridge_mod._normalize(step, record, NOW)

    def test_succeeded_projects_effects_and_duration(self):
        outcome = self._normalize(support.action_record())
        assert outcome.status == "succeeded"
        assert outcome.failure_kind is None
        assert outcome.effects == [{"kind": "world", "ref": "ev-1", "reversible": True}]
        assert outcome.duration_ms == 12
        assert outcome.tool_id == support.REMINDER_CREATE

    def test_failure_kind_values_stay_inside_the_tool_failure_kinds(self):
        for kind in ("transient", "permanent", "timeout", "unavailable", "denied", "invalid"):
            outcome = self._normalize(
                support.action_record(status="failed", failure_kind=kind)
            )
            assert outcome.failure_kind in TOOL_FAILURE_KINDS

    def test_unknown_failure_kind_collapses_to_permanent(self):
        outcome = self._normalize(
            support.action_record(status="failed", failure_kind="not_a_kind")
        )
        assert outcome.failure_kind == "permanent"

    def test_timeout_is_expressed_as_failed_plus_failure_kind(self):
        outcome = self._normalize(
            support.action_record(status="failed", failure_kind="timeout")
        )
        assert outcome.status == "failed"
        assert outcome.failure_kind == "timeout"

    def test_gate_rejections_map_into_the_declared_outcome_value_set(self):
        for gate_reason in (
            "capability_unavailable",
            "permission_denied",
            "invalid_params",
            "pending_confirmation",
            "duplicate",
            "quota_exceeded",
            "effect_already_satisfied",
            "expired",
            "ambiguous_params",
            "disabled",
            "target_not_found",
        ):
            outcome = self._normalize(
                support.action_record(status="cancelled", gate_reason=gate_reason)
            )
            assert outcome.status in PLAN_STEP_OUTCOME_VALUES, gate_reason
        assert (
            self._normalize(
                support.action_record(status="cancelled", gate_reason="permission_denied")
            ).failure_kind
            == "denied"
        )
        assert (
            self._normalize(
                support.action_record(status="cancelled", gate_reason="invalid_params")
            ).failure_kind
            == "invalid"
        )
        assert (
            self._normalize(
                support.action_record(status="planned", gate_reason="pending_confirmation")
            ).status
            == "blocked"
        )

    def test_retrying_action_yields_hold_with_the_retryable_kind(self):
        outcome = self._normalize(
            support.action_record(status="executing", step_status="failed", failure_kind="transient")
        )
        assert outcome.status == "hold"
        assert outcome.failure_kind == "transient"

    def test_observations_are_clipped_by_the_whitelist(self):
        record = support.action_record(
            steps=[
                {
                    "index": 1,
                    "capability": "reminder",
                    "action": "create",
                    "status": "succeeded",
                    "tool_id": support.REMINDER_CREATE,
                    "result": {
                        "status": "succeeded",
                        "observations": {"reminder_id": "ev-1", "internal_debug": "secret"},
                    },
                }
            ]
        )
        outcome = self._normalize(record, observation_keys=("reminder_id",))
        assert outcome.observations == {"reminder_id": "ev-1"}
        assert "internal_debug" not in outcome.observations

    def test_no_declared_keys_means_no_observations_at_all(self):
        outcome = self._normalize(support.action_record())
        assert outcome.observations == {}


class TestReconcile:
    """U8 / D7：`attempt_count` 只在 Action 终态递增 + 回填面。"""

    @staticmethod
    def _outcome(status, *, failure_kind=None, action_id="action-1", at=NOW):
        from app.models.plan import PlanStepOutcome

        return PlanStepOutcome(
            step_index=1,
            status=status,
            at=at,
            action_id=action_id,
            failure_kind=failure_kind,
        )

    def test_attempt_count_increments_on_success(self):
        step = support.spec(1)
        updated = BRIDGE.reconcile(self._outcome("succeeded"), step, max_attempts=2)
        assert updated.attempt_count == 1
        assert updated.status == "in_progress"
        assert updated.last_attempt_at == NOW

    def test_attempt_count_increments_on_action_failure(self):
        step = support.spec(1)
        updated = BRIDGE.reconcile(
            self._outcome("failed", failure_kind="transient"), step, max_attempts=2
        )
        assert updated.attempt_count == 1
        assert updated.status == "in_progress"

    def test_attempt_count_does_not_increment_on_intermediate_states(self):
        step = support.spec(1)
        for status, kind in (("hold", "transient"), ("blocked", "unavailable"), ("skipped", None)):
            updated = BRIDGE.reconcile(
                self._outcome(status, failure_kind=kind, action_id=None),
                step,
                max_attempts=2,
            )
            assert updated.attempt_count == 0, status

    def test_attempt_exhaustion_marks_the_step_failed(self):
        step = support.spec(1, attempt_count=1)
        updated = BRIDGE.reconcile(
            self._outcome("failed", failure_kind="permanent"), step, max_attempts=2
        )
        assert updated.attempt_count == 2
        assert updated.status == "failed"
        assert updated.failure_note == "permanent 第 2 次尝试失败（action=action-1）"

    def test_blocked_denied_marks_the_step_failed_without_retrying(self):
        step = support.spec(1)
        updated = BRIDGE.reconcile(
            self._outcome("blocked", failure_kind="denied"), step, max_attempts=2
        )
        assert updated.status == "failed"
        assert updated.attempt_count == 0

    def test_blocked_pending_confirmation_waits_in_progress(self):
        step = support.spec(1)
        updated = BRIDGE.reconcile(
            self._outcome("blocked", failure_kind=None), step, max_attempts=2
        )
        assert updated.status == "in_progress"
        assert updated.failure_note is None

    def test_skipped_keeps_the_step_untouched(self):
        step = support.spec(1, status="in_progress", attempt_count=1)
        updated = BRIDGE.reconcile(
            self._outcome("skipped", action_id=None), step, max_attempts=2
        )
        assert updated.status == "in_progress"
        assert updated.attempt_count == 1
        assert updated.last_attempt_at is None

    def test_success_clears_a_previous_failure_note(self):
        step = support.spec(1, failure_note="transient 第 1 次尝试失败（action=a）")
        updated = BRIDGE.reconcile(self._outcome("succeeded"), step, max_attempts=2)
        assert updated.failure_note is None

    def test_reconcile_writes_a_copy_only(self):
        step = support.spec(1)
        updated = BRIDGE.reconcile(self._outcome("succeeded"), step, max_attempts=2)
        assert updated is not step
        assert step.attempt_count == 0
        assert step.status == "pending"

    def test_step_index_mismatch_is_a_defect(self):
        with pytest.raises(PlanBridgeDefect):
            BRIDGE.reconcile(self._outcome("succeeded"), support.spec(2), max_attempts=2)

    def test_configuration_window_is_used_by_default(self):
        from app.core.settings import get_settings

        assert get_settings().plan_step_max_attempts == 2
        step = support.spec(1, attempt_count=1)
        updated = PlanExecutorBridge().reconcile(
            self._outcome("failed", failure_kind="permanent"), step
        )
        assert updated.status == "failed"


class TestQuotaAndCooldownAreNotRelaxed:
    """I11：额度与冷却未放宽——闸门拒绝原样归一，不重试、不绕过。"""

    @pytest.mark.asyncio
    async def test_quota_rejection_yields_hold_without_a_second_attempt(self):
        record = support.action_record(status="cancelled", gate_reason="quota_exceeded", steps=[])
        runner = _Recorder(record)
        plan = _ready_plan()
        outcome = await _bridge(runner=runner).execute_step(
            support.goal(), plan, plan.sub_goals[0], _ctx(support.REMINDER_CREATE)
        )
        assert outcome.status == "hold"
        assert len(runner.calls) == 1
        updated = BRIDGE.reconcile(outcome, plan.sub_goals[0], max_attempts=2)
        assert updated.status == "in_progress"
        assert updated.attempt_count == 0

    def test_run_kind_is_the_autonomous_tick_profile(self):
        assert RUN_KIND_AUTONOMOUS_TICK == "autonomous_tick"
