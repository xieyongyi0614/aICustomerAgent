"""PLAN-008 Step 4：计划终态的广播接线（U9~U12 / I6、S5~S8）。

覆盖 Task Detail §9.1 U9~U12、§9.2 I6、§9.3 S5~S8；对应 §8 Step 4 与 §4.2.5 / §4.3.2。

三处与 Task Detail §8 Step 4 的实现核对（按真实源码冻结，已在用例中留痕）

1. **广播挂在 `settle` 的迁移路径上**（§8 Step 4.1 的「目标终态为 completed 时调」）：既有写面
   `goal_observation._complete`（达成）与 `goal_arbitration.check_abandonment`（放弃）**各自已经广播**
   （V2.0 / V2.3.0 既有），而 `settle` 只在「既有写面没结算、由计划层结算」时才执行迁移。无差别地
   再调一次只会重复投递（被 `char:goal_done:{goal_id}` 幂等键挡下，不产生第二条事件，但属冗余调用）；
   挂在迁移路径上覆盖的是唯一缺口。两个既有路径的存在由 `test_..._existing_paths_still_broadcast` 举证。
2. **`settle` 自身不会迁移到 `abandoned`**：`PlanAdvance` 六值决策集（§4.2.5）无该值，放弃由既有
   `goal_arbitration.check_abandonment` 裁决并广播（§4.3.2 第 3 行的「产生方式」即指该既有路径）。
   故 §8 Step 4.2 的「`abandoned` → 同函数」以**映射表 + 该既有路径**两条一起兑现：映射表
   `TERMINAL_BROADCAST_OUTCOMES` 显式含 `abandoned`（计划层若执行了放弃迁移也广播），本版本由
   `check_abandonment` 端到端兑现。
3. **失败不广播（U10）与修订不广播（S8）**：`failed` 不在映射表内；修订（`replanning` 裁决）不产生
   终态迁移，结构上不可能广播——两者各以运行时负例 + 调用点结构断言双重判定。
"""

from datetime import datetime, timedelta

import pytest

from app.application import outbox_consumer
from app.application.agent_runtime.trigger_router import evaluate_event_escalation
from app.core.settings import get_settings
from app.models.observability import DecisionKind
from app.models.plan import PlanAdvance
from app.repositories import goal_repository, outbox_repository
from app.services import goal_arbitration
from app.services.planning import observer as observer_mod
from app.services.planning.observer import PlanObserver

from . import _plan_scan as scan
from . import plan008_support as support
from .plan008_support import (  # noqa: F401  （夹具须进本模块命名空间才被 pytest 收集）
    planning_world_on,
)

OBSERVER = PlanObserver()

BROADCAST_PREFIX = support.BROADCAST_IDEMPOTENCY_PREFIX

GOAL_COMPLETED_EVENT = "goal_completed"


def _advance(goal, plan, decision: str, reason: str = "goal_completed") -> PlanAdvance:
    return PlanAdvance(
        goal_id=goal.id,
        plan_id=plan.id,
        plan_version=plan.version,
        decision=decision,
        reason=reason,
        at=support.NOW,
    )


def _broadcast_rows() -> list:
    return [
        row
        for row in outbox_repository.list_pending(limit=50)
        if row.idempotency_key.startswith(BROADCAST_PREFIX)
    ]


def _goal_events(user_id: str) -> list[dict]:
    return [
        row for row in support.world_event_rows(user_id) if row["type"] == GOAL_COMPLETED_EVENT
    ]


class TestTerminalBroadcast:
    """U9：达成 / 放弃各产生一条 `world_events`（`source=character`）。"""

    def test_completed_transition_broadcasts_one_character_event(
        self, db_session_factory, planning_world_on, make_goal, make_plan
    ):
        goal = make_goal(description="完成广播目标")
        plan = make_plan(goal.id)
        settlement = OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))
        assert settlement.transitioned is True

        rows = _broadcast_rows()
        assert [row.idempotency_key for row in rows] == [f"{BROADCAST_PREFIX}{goal.id}"]
        assert [op["op"] for op in rows[0].payload["world_ops"]] == ["create_event"]
        assert _goal_events(goal.user_id) == []

        stats = outbox_consumer.consume_pending(now=datetime.now())
        assert stats["consumed"] == 1
        events = _goal_events(goal.user_id)
        assert len(events) == 1
        assert events[0]["source"] == "character"
        assert events[0]["importance"] == "normal"
        assert events[0]["payload"]["outcome"] == "completed"
        assert events[0]["payload"]["goal_id"] == goal.id
        assert events[0]["payload"]["outbox_action_id"] == f"{BROADCAST_PREFIX}{goal.id}"

    def test_abandonment_broadcasts_through_the_existing_arbitration_path(
        self, db_session_factory, planning_world_on, make_goal, monkeypatch
    ):
        """§4.3.2 第 3 行：放弃由既有 `check_abandonment` 判并广播（本任务零改动，只做断言）。"""
        goal = make_goal(description="放弃广播目标")
        monkeypatch.setattr(
            goal_arbitration,
            "_last_progress_at",
            lambda _goal, _facts: support.NOW - timedelta(days=40),
        )
        result = goal_arbitration.check_abandonment(
            goal.user_id,
            {"now": support.NOW, "salient_memories": [], "action_history": []},
            support.NOW,
        )
        assert [item["goal_id"] for item in result["abandoned"]] == [goal.id]
        assert goal_repository.get_goal(goal.id).status == "abandoned"

        outbox_consumer.consume_pending(now=datetime.now())
        events = _goal_events(goal.user_id)
        assert len(events) == 1
        assert events[0]["payload"]["outcome"] == "abandoned"
        assert events[0]["importance"] == "low"
        assert events[0]["source"] == "character"

    def test_abandoned_outcome_is_wired_for_a_plan_side_transition(
        self, db_session_factory, planning_world_on, make_goal
    ):
        """映射表显式含 `abandoned`：计划层若执行放弃迁移，广播语义与既有路径一致。"""
        goal = make_goal(description="计划侧放弃目标")
        assert observer_mod.TERMINAL_BROADCAST_OUTCOMES == {
            "completed": "completed",
            "abandoned": "abandoned",
        }
        assert observer_mod.broadcast_goal_terminal(goal, "abandoned") is True
        assert [row.idempotency_key for row in _broadcast_rows()] == [
            f"{BROADCAST_PREFIX}{goal.id}"
        ]
        outbox_consumer.consume_pending(now=datetime.now())
        events = _goal_events(goal.user_id)
        assert events[0]["payload"]["outcome"] == "abandoned"

    def test_repeated_broadcast_is_idempotent(
        self, db_session_factory, planning_world_on, make_goal, make_plan
    ):
        goal = make_goal(description="重复广播目标")
        plan = make_plan(goal.id)
        OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))
        assert observer_mod.broadcast_goal_terminal(goal, "completed") is False
        outbox_consumer.consume_pending(now=datetime.now())
        assert len(_goal_events(goal.user_id)) == 1

    def test_existing_write_faces_still_broadcast_on_their_own_paths(
        self, db_session_factory, planning_world_on, make_goal
    ):
        """既有两条路径的广播未被动过（本任务只加计划层的迁移路径接线）。"""
        sources = {
            "app/services/goal_observation.py": ('"completed"',),
            "app/services/goal_arbitration.py": ('"abandoned"',),
        }
        for relative, fragments in sources.items():
            text = (support.repo_root() / relative).read_text(encoding="utf-8")
            assert "register_goal_event" in text
            for fragment in fragments:
                assert fragment in text.split("register_goal_event", 1)[1][:200]


class TestNoBroadcastNegatives:
    """U10 / S7 / S8：失败不广播、修订不广播（均以运行时负例判定）。"""

    def test_failed_transition_does_not_broadcast(
        self, db_session_factory, planning_world_on, make_goal, make_plan
    ):
        goal = make_goal(description="失败不广播目标")
        plan = make_plan(goal.id)
        settlement = OBSERVER.settle(
            goal, plan, _advance(goal, plan, "failed", reason="plan_exhausted")
        )
        assert settlement.transitioned is True
        assert goal_repository.get_goal(goal.id).status == "failed"
        assert observer_mod.broadcast_goal_terminal(goal, "failed") is False
        outbox_consumer.consume_pending(now=datetime.now())
        assert _goal_events(goal.user_id) == []

    @pytest.mark.parametrize(
        "decision", ("advanced", "hold", "replanning", "skipped")
    )
    def test_non_terminal_decisions_never_broadcast(
        self, db_session_factory, planning_world_on, make_goal, make_plan, decision
    ):
        """修订（`replanning`）与其余非终态裁决都不产生世界事件（S8 的裁决面形态）。"""
        goal = make_goal(description=f"非终态不广播-{decision}")
        plan = make_plan(goal.id)
        settlement = OBSERVER.settle(
            goal, plan, _advance(goal, plan, decision, reason="plan_step_advanced")
        )
        assert settlement.transitioned is False
        outbox_consumer.consume_pending(now=datetime.now())
        assert _goal_events(goal.user_id) == []

    def test_already_settled_goal_is_not_broadcast_by_the_planning_layer(
        self, db_session_factory, planning_world_on, make_goal, make_plan
    ):
        goal = make_goal(description="既有写面已结算目标")
        plan = make_plan(goal.id)
        goal_repository.complete_goal(goal.id)
        settlement = OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))
        assert settlement.transitioned is False
        assert _broadcast_rows() == []

    def test_broadcast_is_wired_only_on_the_transition_path(self):
        """结构断言：`broadcast_goal_terminal` 在计划包内只有 `_transition` 一个调用点。"""
        source = (scan.PLANNING_PACKAGE_DIR / "observer.py").read_text(encoding="utf-8")
        assert source.count("broadcast_goal_terminal(") == 2
        transition_body = source.split("def _transition(", 1)[1]
        assert "broadcast_goal_terminal(" in transition_body
        settle_body = source.split("def settle(", 1)[1].split("def _transition(", 1)[0]
        assert "broadcast_goal_terminal(" not in settle_body


class TestBroadcastFailureDiscipline:
    """U12 / D15：广播失败（抛错 / Flag off）不回滚计划终态。"""

    def test_broadcast_exception_does_not_roll_back_the_terminal_state(
        self, db_session_factory, planning_world_on, make_goal, make_plan, monkeypatch
    ):
        def _boom(*args, **kwargs):
            raise RuntimeError("outbox 不可用")

        monkeypatch.setattr(
            "app.services.world.event_bridge.register_goal_event", _boom
        )
        goal = make_goal(description="广播失败不回滚目标")
        plan = make_plan(goal.id)
        settlement = OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))
        assert settlement.transitioned is True
        assert settlement.goal_status == "completed"
        assert goal_repository.get_goal(goal.id).status == "completed"

    def test_event_system_flags_off_write_nothing(
        self, db_session_factory, planning_world_on, make_goal, make_plan, override_settings
    ):
        override_settings(
            )
        goal = make_goal(description="事件链关闭目标")
        plan = make_plan(goal.id)
        settlement = OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))
        assert settlement.transitioned is True
        assert goal_repository.get_goal(goal.id).status == "completed"
        assert outbox_repository.list_pending(limit=50) == []
        assert _goal_events(goal.user_id) == []

    def test_audit_and_attribution_survive_a_failed_broadcast(
        self, db_session_factory, planning_world_on, make_goal, make_plan, monkeypatch
    ):
        captured: list = []
        monkeypatch.setattr(
            "app.application.observability.on_decision", lambda record: captured.append(record)
        )
        monkeypatch.setattr(
            "app.services.world.event_bridge.register_goal_event",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("失败")),
        )
        goal = make_goal(description="广播失败审计目标")
        plan = make_plan(goal.id)
        OBSERVER.settle(goal, plan, _advance(goal, plan, "completed"))
        triggers = [record.trigger for record in captured]
        assert observer_mod.STEP_NAME in triggers
        assert "goal_arbitration" in triggers
        assert all(record.kind == DecisionKind.GOAL_LIFECYCLE for record in captured)


class TestWorldEventTypeValueSet:
    """U11 / I6 / §10.3：`world_events.type` 值域未扩，且落点可被既有升级链路消费。"""

    def test_event_bridge_produces_only_the_two_frozen_event_types(self):
        import ast

        path = scan.PLANNING_PACKAGE_DIR.parent / "world" / "event_bridge.py"
        produced: set[str] = set()
        for node in ast.walk(scan.tree(path)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "_register_world_op" or len(node.args) < 2:
                continue
            event_type = node.args[1]
            if isinstance(event_type, ast.Constant) and isinstance(event_type.value, str):
                produced.add(event_type.value)
        assert produced == {"goal_completed", "interest_emerged"}

    def test_escalation_whitelist_contains_goal_completed(self, planning_world_on):
        settings = get_settings()
        types = {item.strip() for item in settings.world_event_escalation_types.split(",")}
        assert GOAL_COMPLETED_EVENT in types

    def test_i6_the_broadcast_lands_on_the_existing_escalation_link(self, planning_world_on):
        assert evaluate_event_escalation(GOAL_COMPLETED_EVENT) is True
        assert evaluate_event_escalation("plan_revised") is False

    def test_terminal_broadcast_outcomes_reuse_existing_values(self):
        assert set(observer_mod.TERMINAL_BROADCAST_OUTCOMES.values()) == {
            "completed",
            "abandoned",
        }
        assert "failed" not in observer_mod.TERMINAL_BROADCAST_OUTCOMES
