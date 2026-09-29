"""PLAN-009 Step 4：政策闸（R1~R8 零豁免）与幂等（`has_memory_effect` 泛化）。

覆盖 Task Detail §9.1 U4 / U7 / U9、§9.2 I1 ~ I3、§9.3 S1 ~ S4 / S6；对应 §8 Step 4 与
§6.4 / §7.5.5。

**G-MEMORY**：失败 / 放弃类候选的 `source`（`user_derived`）与 `importance`（≥ floor）必须能通过
R1——若被 R1 丢弃则用例失败（这正是「`ai_inferred` 直觉最自然却恒定被拒」的守卫）。
"""

import pytest

from app.models.goal import GoalPlanRecord
from app.models.plan import PlanAdvance
from app.repositories import goal_repository
from app.services.memory import policy as policy_gate
from app.services.planning import memory_policy as plan_memory_policy
from app.services.planning import observer as observer_mod
from app.services.planning.observer import PlanObserver
from app.services.tool import memory_policy as tool_memory_policy

from . import _plan_scan as scan
from . import plan009_support as support
from .plan009_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    planning_memory_on,
)

OBSERVER = PlanObserver()

MODULE_PATH = support.module_path("memory_policy.py")

DEPOSIT_EVENTS = (
    plan_memory_policy.EVENT_PLAN_COMPLETED,
    plan_memory_policy.EVENT_PLAN_FAILED,
    plan_memory_policy.EVENT_PLAN_ABANDONED,
)


def _advance(goal, plan, decision: str, reason: str = "plan_step_advanced") -> PlanAdvance:
    return PlanAdvance(
        goal_id=goal.id,
        plan_id=plan.id,
        plan_version=plan.version,
        decision=decision,
        reason=reason,
        at=support.NOW,
    )


def _terminal_plan(goal, specs=None) -> GoalPlanRecord:
    return support.plan(specs, goal_id=goal.id)


class TestGMemoryNotMisjudged:
    """U4：G-MEMORY——三类终态候选的 `source` / `importance` 能通过 R1。"""

    @pytest.mark.parametrize("event_kind", DEPOSIT_EVENTS)
    def test_candidate_passes_r1_for_every_terminal(self, event_kind, monkeypatch):
        support.install_ingest_stub(monkeypatch)
        candidate = plan_memory_policy.build_candidate(
            support.goal(support.FAILED_DESCRIPTION), support.plan(), event_kind
        )
        assert candidate.source == "user_derived"
        assert candidate.source != "ai_inferred"

        report = policy_gate.apply_policy([candidate], [])

        assert report.saved == [candidate]
        assert report.discarded == []
        assert [outcome.rule for outcome in report.outcomes] == [""]

    @pytest.mark.parametrize("event_kind", DEPOSIT_EVENTS)
    def test_importance_clears_the_r6_threshold(self, event_kind):
        from app.core.settings import get_settings

        decision = plan_memory_policy.get_plan_memory_policy().decide(event_kind)
        assert decision.importance >= get_settings().memory_importance_threshold
        assert tool_memory_policy.DEFAULT_CONFIDENCE >= get_settings().memory_min_confidence

    def test_the_same_content_with_ai_inferred_is_discarded_by_r1(self, monkeypatch):
        """对照组：把同一候选的 `source` 换成 `ai_inferred`，R1 立即拒收（G-MEMORY 的反证）。"""
        support.install_ingest_stub(monkeypatch)
        candidate = plan_memory_policy.build_candidate(
            support.goal(), support.plan(), plan_memory_policy.EVENT_PLAN_COMPLETED
        )
        report = policy_gate.apply_policy(
            [candidate.model_copy(update={"source": "ai_inferred"})], []
        )
        assert [outcome.rule for outcome in report.discarded] == ["R1"]


class TestPolicyGateDiscard:
    """U9 / D10：政策闸未通过 → 丢弃，**不回滚计划执行**。"""

    def test_r8_discard_leaves_the_plan_terminal_untouched(
        self, db_session_factory, planning_memory_on, make_goal
    ):
        goal = make_goal(description="把那个东西准备好")
        plan = _terminal_plan(goal)

        settlement = OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))

        assert settlement.transitioned is True
        assert goal_repository.get_goal(goal.id).status == "completed"
        assert support.memories(goal.user_id) == []

    @pytest.mark.parametrize(
        "description,rule",
        (
            ("今天提醒我喝水", "R4"),
            ("把那个东西准备好", "R8"),
        ),
    )
    def test_one_off_and_unresolved_reference_are_discarded(
        self, db_session_factory, planning_memory_on, make_goal, monkeypatch, description, rule
    ):
        probe = support.install_delivery_probe(monkeypatch)
        goal = make_goal(description=description)
        plan = _terminal_plan(goal)

        result = observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")

        assert result is None
        assert probe.order == ["ingest_from_goal_completion", "apply_policy"]
        assert support.memories(goal.user_id) == []

    def test_policy_failure_is_captured_and_the_terminal_state_survives(
        self, db_session_factory, planning_memory_on, make_goal, monkeypatch
    ):
        def _boom(*args, **kwargs):
            raise RuntimeError("政策闸不可用")

        monkeypatch.setattr(policy_gate, "apply_policy", _boom)
        goal = make_goal(description="政策闸故障目标")
        plan = _terminal_plan(goal)

        settlement = OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))

        assert settlement.transitioned is True
        assert goal_repository.get_goal(goal.id).status == "completed"
        assert support.memories(goal.user_id) == []


class TestTerminalDelivery:
    """I2 / S1 ~ S3：三类终态各沉淀恰好一条，内容语义与边界表逐条一致。"""

    def test_completed_deposits_exactly_one_memory(
        self, db_session_factory, planning_memory_on, make_goal
    ):
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        plan = _terminal_plan(goal)

        settlement = OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))

        assert settlement.transitioned is True
        stored = support.memories(goal.user_id)
        assert len(stored) == 1
        assert stored[0].content == f"完成了目标：{support.COMPLETED_DESCRIPTION}"
        assert stored[0].type == tool_memory_policy.DEFAULT_MEMORY_TYPE
        assert stored[0].importance == plan_memory_policy.PLAN_COMPLETED_IMPORTANCE
        assert stored[0].source == "user_derived"

    def test_failed_deposits_exactly_one_memory_with_unfinished_semantics(
        self, db_session_factory, planning_memory_on, make_goal
    ):
        goal = make_goal(description=support.FAILED_DESCRIPTION)
        plan = _terminal_plan(goal)

        settlement = OBSERVER.settle(
            goal, plan, _advance(goal, plan, "failed", reason="plan_exhausted")
        )

        assert settlement.transitioned is True
        stored = support.memories(goal.user_id)
        assert len(stored) == 1
        assert stored[0].content == f"上次没能帮用户完成：{support.FAILED_DESCRIPTION}"
        assert stored[0].source == "user_derived"
        assert stored[0].importance >= 0.6

    def test_abandoned_is_wired_for_a_plan_side_delivery(
        self, db_session_factory, planning_memory_on, make_goal
    ):
        """§4.3.2 第 3 行：映射表显式含 `abandoned`（既有 `check_abandonment` 路径端到端兑现）。"""
        goal = make_goal(description=support.FAILED_DESCRIPTION)
        plan = _terminal_plan(goal)

        result = observer_mod.deliver_goal_terminal_memory(goal, plan, "abandoned")

        assert result is not None
        stored = support.memories(goal.user_id)
        assert len(stored) == 1
        assert stored[0].content == f"上次没能帮用户完成：{support.FAILED_DESCRIPTION}"

    def test_terminal_memory_mapping_covers_every_deposit_event(self):
        assert observer_mod.TERMINAL_MEMORY_EVENTS == {
            "completed": "plan_completed",
            "failed": "plan_failed",
            "abandoned": "plan_abandoned",
        }
        assert set(observer_mod.TERMINAL_MEMORY_EVENTS.values()) == set(DEPOSIT_EVENTS)

    @pytest.mark.parametrize("outcome", ("advanced", "hold", "replanning", "skipped"))
    def test_non_terminal_outcomes_never_deliver(
        self, db_session_factory, planning_memory_on, make_goal, outcome
    ):
        goal = make_goal(description="非终态不沉淀目标")
        plan = _terminal_plan(goal)
        assert observer_mod.deliver_goal_terminal_memory(goal, plan, outcome) is None
        assert support.memories(goal.user_id) == []


class TestIdempotency:
    """U7 / S6：同一次执行重复投递不产生第二条记忆（`has_memory_effect` 泛化生效）。"""

    def test_receipt_is_registered_on_the_plan_scoped_record(
        self, db_session_factory, planning_memory_on, make_goal
    ):
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        plan = _terminal_plan(goal)
        support.seed_plan_record(
            user_id=goal.user_id,
            goal_id=goal.id,
            dedupe_key=support.dedupe_key(goal.id),
        )

        result = observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")

        record = support.stored_record()
        assert record is not None
        assert tool_memory_policy.has_memory_effect(record) is True
        assert support.receipt_effects(record) == [
            {
                "kind": "memory",
                "ref": result["memory_id"],
                "detail": plan_memory_policy.PLAN_MEMORY_RECEIPT_DETAIL,
            }
        ]

    def test_repeated_delivery_with_a_receipt_produces_no_second_memory(
        self, db_session_factory, planning_memory_on, make_goal, monkeypatch
    ):
        probe = support.install_delivery_probe(monkeypatch)
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        plan = _terminal_plan(goal)
        support.seed_plan_record(
            user_id=goal.user_id,
            goal_id=goal.id,
            dedupe_key=support.dedupe_key(goal.id),
        )

        first = observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")
        second = observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")

        assert first is not None
        assert second is None
        assert probe.order.count("create_memory") == 1
        assert probe.order.count("apply_policy") == 1
        assert len(support.memories(goal.user_id)) == 1

    def test_repeated_delivery_without_a_record_falls_back_to_r7(
        self, db_session_factory, planning_memory_on, make_goal
    ):
        """无计划域台账行时（从未执行过步骤）：幂等由政策闸 R7 兜底，仍不产生第二条。"""
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        plan = _terminal_plan(goal)

        first = observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")
        second = observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")

        assert first is not None
        assert second is None
        assert len(support.memories(goal.user_id)) == 1

    def test_a_tool_side_memory_effect_does_not_count_as_the_terminal_receipt(
        self, db_session_factory, planning_memory_on, make_goal
    ):
        """正交性负例：工具侧 deposit 的 `kind=memory` 不得抑制终态记忆（判据 C 的回归守卫）。"""
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        plan = _terminal_plan(goal)
        support.seed_plan_record(
            user_id=goal.user_id,
            goal_id=goal.id,
            dedupe_key=support.dedupe_key(goal.id),
            effects=[
                {"kind": "memory", "ref": "tool-memory-1", "detail": support.TOOL_SIDE_MEMORY_DETAIL}
            ],
        )
        assert tool_memory_policy.has_memory_effect(support.stored_record()) is True

        result = observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")

        assert result is not None
        assert len(support.memories(goal.user_id)) == 1


class TestZeroBypass:
    """I3 / D8：全部候选经 `apply_policy`，无旁路写库（静态 + 运行时断言）。"""

    def test_runtime_order_is_ingest_then_policy_then_write(
        self, db_session_factory, planning_memory_on, make_goal, monkeypatch
    ):
        probe = support.install_delivery_probe(monkeypatch)
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        plan = _terminal_plan(goal)

        observer_mod.deliver_goal_terminal_memory(goal, plan, "completed")

        assert probe.order == [
            "ingest_from_goal_completion",
            "apply_policy",
            "create_memory",
        ]
        assert probe.policy_candidates[0][0].source == "user_derived"
        assert probe.saved[0]["source"] == "user_derived"

    def test_no_write_surface_is_called_without_the_policy_gate(
        self, db_session_factory, planning_memory_on, make_goal, monkeypatch
    ):
        probe = support.install_delivery_probe(monkeypatch)
        monkeypatch.setattr(
            policy_gate, "apply_policy", lambda *args, **kwargs: policy_gate.PolicyReport()
        )
        goal = make_goal(description=support.COMPLETED_DESCRIPTION)
        plan = _terminal_plan(goal)

        assert observer_mod.deliver_goal_terminal_memory(goal, plan, "completed") is None
        assert probe.order == ["ingest_from_goal_completion"]
        assert support.memories(goal.user_id) == []

    def test_module_holds_a_single_gate_entry_and_a_single_write_entry(self):
        code = scan.code_text(MODULE_PATH)
        assert code.count("apply_policy(") == 1
        assert code.count("create_memory(") == 1
        assert scan.code_violations(
            MODULE_PATH,
            (
                "session.add",
                "session.commit",
                "session.execute",
                "session.query",
                "INSERT INTO",
                "DELETE FROM",
            ),
        ) == []
