"""PLAN-007 Step 3：`_apply_plan_adjustments` 调制语义与八步裁决顺序零改动。

覆盖 Task Detail §9.1 U7~U10 与 §9.2 I2、§9.3 S2 / S3 的可判定部分。

纪律复述（§4.3.2 / §6.3 D9~D11）：本函数只**收紧**、绝不**放行**——空包 / `current_step
is None` / 动作不同 / 非 `act` 一律原样返回；不改八步裁决顺序、不改 `TRIGGER_PRIORITY`
数学；`HIGH_PRIORITY_OVERRIDE`（P0 / P1）仍可越过本抑制。
"""

from datetime import timedelta

from app.core.settings import get_settings
from app.models.autonomy import AutonomyVerdict
from app.services import autonomy_policy

from . import plan007_support as support

NOW = support.NOW
SIGNAL = support.signal()
NOTE = "计划推进中，暂不抢同一动作"


def _evaluate(snapshot, signal=SIGNAL, now=NOW):
    return autonomy_policy.evaluate(signal, snapshot, get_settings(), now)


class TestModulationSemantics:
    """U7 / U8 / U9：空包零影响、同动作被抑制、不同动作不受影响。"""

    def test_empty_packet_returns_the_verdict_untouched(self):
        baseline = _evaluate(support.act_snapshot())
        verdict = autonomy_policy._apply_plan_adjustments(
            baseline, support.act_snapshot(plan_facts={})
        )
        assert verdict is baseline
        assert verdict.decision == "act"

    def test_no_advancing_step_returns_the_verdict_untouched(self):
        """§4.3.1：全部步骤终态（`current_step=None`）视为无推进中的计划。"""
        baseline = _evaluate(support.act_snapshot())
        verdict = autonomy_policy._apply_plan_adjustments(
            baseline, support.barrier_snapshot({'current_step': None})
        )
        assert verdict is baseline
        assert verdict.decision == "act"

    def test_the_same_action_is_suppressed(self):
        verdict = _evaluate(support.barrier_snapshot())
        assert verdict.decision == "wait"
        assert verdict.reason == f"触发 conversation_inactivity，存在 user_care 目标；{NOTE}"

    def test_suppression_reason_is_bounded_and_keeps_the_trigger(self):
        verdict = _evaluate(support.barrier_snapshot())
        assert len(verdict.reason) <= 60
        assert verdict.trigger is not None and verdict.trigger.type == SIGNAL.type
        assert verdict.intention is None

    def test_a_different_action_is_not_suppressed(self):
        verdict = _evaluate(
            support.barrier_snapshot({'current_action_type': support.OTHER_ACTION})
        )
        assert verdict.decision == "act"
        assert verdict.intention == support.CHECK_IN_INTENTION
        assert NOTE not in verdict.reason

    def test_an_intention_without_an_action_identity_is_not_suppressed(self):
        """`relationship` 目标的意图（`repair_rapport`）不在 `PROACTIVE_ACTION_MAP` 内。"""
        verdict = _evaluate(
            support.act_snapshot(
                selected_goal_type="relationship",
                plan_facts=support.plan_facts(),
            )
        )
        assert verdict.decision == "act"
        assert verdict.intention == "repair_rapport"

    def test_non_act_verdicts_are_returned_untouched(self):
        for snapshot_overrides in (
            {"intimacy": 0.1},
            {"mood": "tired"},
            {"goal_degraded": True},
        ):
            blocked = _evaluate(support.act_snapshot(**snapshot_overrides))
            with_packet = _evaluate(
                support.act_snapshot(
                    plan_facts=support.plan_facts(), **snapshot_overrides
                )
            )
            assert blocked.model_dump() == with_packet.model_dump()

    def test_the_modulation_never_loosens_a_verdict(self):
        """只收紧：调制前后 `decision` 只允许 `act → wait`，不存在反向。"""
        baseline = autonomy_policy.AutonomyVerdict(decision="ignore", reason="静音时段")
        assert (
            autonomy_policy._apply_plan_adjustments(
                baseline, support.barrier_snapshot()
            )
            is baseline
        )
        waiting = autonomy_policy.AutonomyVerdict(decision="wait", reason="冷却中")
        assert (
            autonomy_policy._apply_plan_adjustments(
                waiting, support.barrier_snapshot()
            )
            is waiting
        )

    def test_an_act_verdict_without_a_trigger_is_not_suppressed(self):
        """`trigger` 缺失时按 P3 处理（不臆造高优先级），仍受抑制。"""
        pending = AutonomyVerdict(
            decision="act", reason="触发", intention=support.CHECK_IN_INTENTION
        )
        verdict = autonomy_policy._apply_plan_adjustments(
            pending, support.barrier_snapshot()
        )
        assert verdict.decision == "wait"

    def test_intention_action_lookup_is_the_single_authority(self):
        from app.character.asuna.action import PROACTIVE_ACTION_MAP

        assert (
            autonomy_policy._intention_action_type(support.CHECK_IN_INTENTION)
            == PROACTIVE_ACTION_MAP[support.CHECK_IN_INTENTION]
            == support.REMINDER_ACTION
        )
        assert autonomy_policy._intention_action_type(None) is None
        assert autonomy_policy._intention_action_type("") is None
        assert autonomy_policy._intention_action_type("repair_rapport") is None


class TestHighPriorityOverride:
    """U10 / S3：`HIGH_PRIORITY_OVERRIDE`（P0 / P1）仍越过计划抑制。"""

    def test_p0_trigger_crosses_the_plan_suppression(self):
        verdict = _evaluate(
            support.barrier_snapshot(), signal=support.signal("scheduled_followup")
        )
        assert autonomy_policy.trigger_priority(support.signal("scheduled_followup")) == "P0"
        assert verdict.decision == "act"
        assert NOTE not in verdict.reason

    def test_p1_trigger_crosses_the_plan_suppression(self):
        verdict = _evaluate(
            support.barrier_snapshot(), signal=support.signal("action_due")
        )
        assert autonomy_policy.trigger_priority(support.signal("action_due")) == "P1"
        assert verdict.decision == "act"

    def test_p3_trigger_does_not_cross(self):
        verdict = _evaluate(
            support.barrier_snapshot(), signal=support.signal("conversation_inactivity")
        )
        assert verdict.decision == "wait"

    def test_the_override_constant_is_unchanged(self):
        assert autonomy_policy.HIGH_PRIORITY_OVERRIDE == frozenset({"P0", "P1"})


EIGHT_STEP_PROBES = (
    ("generating", {"generating": True}, "wait", "用户正在对话"),
    ("quiet_hours", {}, "ignore", "静音时段"),
    (
        "cooldown",
        {"last_proactive_at": NOW - timedelta(minutes=10)},
        "wait",
        "冷却中",
    ),
    ("attempt_cap", {"attempt_count": 2}, "ignore", "本集期已达上限"),
    ("active_action", {"has_active_action": True}, "wait", "上一条主动还未处理"),
    ("shallow_relationship", {"intimacy": 0.2}, "ignore", "关系尚浅，不主动打扰"),
    ("character_state", {"mood": "tired"}, "ignore", "角色状态不宜"),
    ("no_motive", {"goal_degraded": True}, "ignore", "无主动动机"),
)
"""八步闸门的逐条探针（顺序即 `evaluate` 的短路顺序，由 `test_*` 逐条冻结）。"""


class TestEightStepAdjudicationOrder:
    """I2 / D10：八步裁决顺序零改动，且 `plan_facts` 对八步**零影响**。"""

    def test_the_eight_gates_short_circuit_in_the_frozen_order(self):
        observed = []
        for _name, overrides, decision, reason in EIGHT_STEP_PROBES:
            snapshot = support.act_snapshot(**overrides)
            if _name == "quiet_hours":
                verdict = _evaluate(snapshot, now=NOW.replace(hour=4))
            else:
                verdict = _evaluate(snapshot)
            observed.append((verdict.decision, verdict.reason))
            assert (verdict.decision, verdict.reason) == (decision, reason), _name
        assert observed == [
            (decision, reason) for _name, _o, decision, reason in EIGHT_STEP_PROBES
        ]

    def test_the_packet_never_changes_any_of_the_eight_gates(self):
        """把事实包塞进每一条闸门探针：八步输出逐字节一致（闸门只看既有信号）。"""
        for name, overrides, decision, reason in EIGHT_STEP_PROBES:
            without = support.act_snapshot(**overrides)
            with_packet = support.act_snapshot(plan_facts=support.plan_facts(), **overrides)
            now = NOW.replace(hour=4) if name == "quiet_hours" else NOW
            left = _evaluate(without, now=now)
            right = _evaluate(with_packet, now=now)
            assert left.model_dump() == right.model_dump(), name
            assert (right.decision, right.reason) == (decision, reason), name

    def test_the_act_path_is_the_only_tail_the_modulation_touches(self):
        verdict = _evaluate(
            support.act_snapshot(plan_facts=support.plan_facts()),
        )
        assert verdict.decision == "wait"
        assert verdict.reason.startswith("触发 conversation_inactivity")

    def test_the_modulation_runs_after_the_four_fact_segments(self):
        """调制链顺序：world → action → tool → tool_insights → plan → relationship。"""
        import re

        tail = _policy_source().split("reason = f\"触发 {signal.type}", 1)[1]
        tail = tail.split("def ", 1)[0]
        chain = re.findall(r"_apply_[a-z_]+", tail)
        assert chain == [
            "_apply_world_adjustments",
            "_apply_action_adjustments",
            "_apply_tool_adjustments",
            "_apply_tool_insight_adjustments",
            "_apply_plan_adjustments",
            "_apply_relationship_rules",
        ]


def _policy_source() -> str:
    from pathlib import Path

    return Path(autonomy_policy.__file__).read_text(encoding="utf-8")
