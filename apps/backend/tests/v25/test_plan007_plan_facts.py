"""PLAN-007 Step 1 / Step 2：`plan_facts` 字段契约、装配（一处 / 同源）、降级与门控。

覆盖 Task Detail §9.1 U1~U6 / U11 / U12 与 §9.2 I7 / I10 / I11 的可判定部分；
策略侧调制（Step 3）见 `test_plan007_policy.py`，静态装配点唯一性与纯函数纪律见
`test_plan007_static_scan.py`，端到端竞争场景见 `test_plan007_e2e.py`。

契约演进留痕（裁决经用户确认）：§4.2.1 原定六键，但 §4.3.2 的「同动作」判定需要
**计划当前步的动作身份**，六键不含该信息（策略层是纯函数，不得反读计划）。故 `plan_facts`
为**七键**（新增标量 `current_action_type`），有界性、单目标、只读、降级四项纪律不变。
"""

from datetime import datetime, timedelta

import pytest

from app.application import autonomy_engine
from app.core.settings import get_settings
from app.models.goal import SubGoalSpec
from app.models.plan import PLAN_ADVANCE_DECISIONS
from app.repositories import decision_repository, goal_repository
from app.engines import autonomy as autonomy_policy

from . import plan007_support as support

USER = support.USER
NOW = support.NOW

PRIOR_V25_FIELDS = (
    "generating",
    "has_active_action",
    "last_proactive_at",
    "attempt_count",
    "intimacy",
    "tension",
    "mood",
    "current_activity",
    "selected_goal_type",
    "goal_degraded",
    "extra_flags",
    "world_facts",
    "action_facts",
    "tool_facts",
    "tool_insights",
    "respect",
    "comfort",
    "conflict_status",
    "neglect_active",
    "unlocks",
    "trust",
    "stage",
    "relationship_patterns",
)
"""V2.4.0 的既有 23 字段（顺序与默认值冻结，见 `test_existing_fields_keep_order_and_defaults`）。"""


def _plans_down(*_args, **_kwargs):
    """只读入口故障注入：装配必须降级为空包且不抛出。"""
    raise RuntimeError("plans down")


@pytest.fixture
def authority_on(override_settings):
    """装配面锚点（历史名保留）：子闸已随开关体系删除，只钉世界面。"""
    override_settings()
    return True


class TestSnapshotFieldContract:
    """U1 / U11：字段位置、默认空包、不含优先级与工具细节。"""

    def test_plan_facts_defaults_to_an_empty_dict(self):
        assert autonomy_policy.PolicySnapshot().plan_facts == {}

    def test_existing_fields_keep_order_and_defaults(self):
        fields = tuple(autonomy_policy.PolicySnapshot.__dataclass_fields__)
        assert fields[:-1] == PRIOR_V25_FIELDS
        assert fields[-1] == "plan_facts"
        assert len(fields) == len(PRIOR_V25_FIELDS) + 1 == 24

    def test_declared_key_contract_is_the_seventh_field_source_of_truth(self):
        assert autonomy_policy.PLAN_FACTS_KEYS == (
            "active_goal_id",
            "plan_version",
            "current_step",
            "current_action_type",
            "steps_total",
            "blocked_steps",
            "last_advanced_at",
        )
        assert len(autonomy_policy.PLAN_FACTS_KEYS) == 7

    def test_plan_facts_carries_no_priority_or_tool_detail(self):
        assert "priority" not in autonomy_policy.PLAN_FACTS_KEYS
        assert "tool_id" not in autonomy_policy.PLAN_FACTS_KEYS
        assert "params" not in autonomy_policy.PLAN_FACTS_KEYS
        assert not any("tool" in key for key in autonomy_policy.PLAN_FACTS_KEYS)

    def test_unknown_keys_are_never_read_by_the_policy(self):
        """事实包是按名取值：未知键既不参与调制，也不改变裁决。"""
        base = autonomy_policy.evaluate(
            support.signal(),
            support.act_snapshot(plan_facts=support.plan_facts()),
            None,
            NOW,
        )
        extra = autonomy_policy.evaluate(
            support.signal(),
            support.act_snapshot(plan_facts=support.plan_facts(priority=0, tool_id="x")),
            None,
            NOW,
        )
        assert base.model_dump() == extra.model_dump()
        assert extra.decision == "wait"


class TestAssemblyShapeAndValues:
    """U2 / U3：七键形状（无无界列表）+ 各字段可追溯到具体读取入口。"""

    def test_shape_is_flat_and_bounded(self, authority_on, db_session_factory):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        facts = autonomy_engine._collect_plan_facts(USER, NOW)
        assert tuple(facts) == autonomy_policy.PLAN_FACTS_KEYS
        assert all(not isinstance(value, (list, dict, tuple)) for value in facts.values())

    def test_field_values_are_traceable_to_their_read_entry(
        self, authority_on, db_session_factory
    ):
        goal = support.seed_layered_goal(USER)
        steps = [
            support.spec(1, capability="query_environment", status="done"),
            support.spec(2, capability=support.REMINDER_ACTION),
            support.spec(3, capability=support.OTHER_ACTION, depends_on=[2]),
        ]
        support.seed_plan(goal.id, steps, version=2)
        support.seed_advance(goal.id, at=NOW - timedelta(hours=1), plan_version=2)

        facts = autonomy_engine._collect_plan_facts(USER, NOW)

        assert facts["active_goal_id"] == goal.id
        assert facts["plan_version"] == 2
        assert facts["current_step"] == 2
        assert facts["current_action_type"] == support.REMINDER_ACTION
        assert facts["steps_total"] == len(steps)
        assert facts["blocked_steps"] == 0
        assert facts["last_advanced_at"] == (NOW - timedelta(hours=1)).isoformat()

    def test_current_step_is_none_when_every_step_is_terminal(
        self, authority_on, db_session_factory
    ):
        """§4.3.1：全部步骤终态 → 视为无推进中的计划（抑制不生效）。"""
        goal = support.seed_layered_goal(USER)
        support.seed_plan(
            goal.id,
            [support.spec(1, status="done"), support.spec(2, status="failed")],
        )
        facts = autonomy_engine._collect_plan_facts(USER, NOW)
        assert facts["current_step"] is None
        assert facts["current_action_type"] is None
        assert facts["steps_total"] == 2

    def test_blocked_steps_counts_the_scheduler_verdict(
        self, authority_on, db_session_factory
    ):
        """`blocked_steps` 取自 `PlanScheduler.blocked_reason`（0 = 有可执行步；1 = 三类阻塞之一）。"""
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id, [support.spec(1)])
        assert autonomy_engine._collect_plan_facts(USER, NOW)["blocked_steps"] == 0

        in_cooldown = support.spec(
            1, last_attempt_at=NOW - timedelta(minutes=5)
        )
        assert (
            autonomy_engine._blocked_steps(
                support.plan([in_cooldown]), USER, NOW
            )
            == 1
        )

    def test_last_advanced_at_ignores_other_decisions_and_other_goals(
        self, authority_on, db_session_factory
    ):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        support.seed_advance(goal.id, decision="hold", at=NOW - timedelta(hours=3))
        support.seed_advance("other-goal", at=NOW - timedelta(hours=2))
        assert autonomy_engine._last_advanced_at(USER, goal.id) is None

        support.seed_advance(goal.id, at=NOW - timedelta(minutes=30))
        assert autonomy_engine._last_advanced_at(USER, goal.id) == (
            NOW - timedelta(minutes=30)
        ).isoformat()

    def test_last_advanced_at_is_the_most_recent_of_several(
        self, authority_on, db_session_factory
    ):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        for hours in (5, 1, 3):
            support.seed_advance(goal.id, at=NOW - timedelta(hours=hours))
        assert autonomy_engine._last_advanced_at(USER, goal.id) == (
            NOW - timedelta(hours=1)
        ).isoformat()

    def test_advance_decision_constant_stays_inside_the_frozen_value_set(self):
        assert autonomy_engine.PLAN_ADVANCE_DECISION_ADVANCED in PLAN_ADVANCE_DECISIONS

    def test_advance_scan_is_bounded(self):
        assert autonomy_engine.PLAN_FACTS_ADVANCE_SCAN_LIMIT <= 200


class TestPlanSelection:
    """U4 / U5：多计划取最近 `updated_at`；无 active 计划为空包。"""

    def test_the_most_recent_plan_wins(self, authority_on, db_session_factory):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(
            goal.id,
            [support.spec(1, capability=support.OTHER_ACTION)],
            plan_id="plan7-old",
            updated_at=NOW - timedelta(hours=6),
        )
        support.seed_plan(
            goal.id,
            [support.spec(1, capability=support.REMINDER_ACTION)],
            plan_id="plan7-new",
            version=2,
            updated_at=NOW - timedelta(minutes=6),
        )
        facts = autonomy_engine._collect_plan_facts(USER, NOW)
        assert facts["plan_version"] == 2
        assert facts["current_action_type"] == support.REMINDER_ACTION

    def test_no_active_plan_yields_an_empty_packet(
        self, authority_on, db_session_factory
    ):
        support.seed_layered_goal(USER)
        assert autonomy_engine._collect_plan_facts(USER, NOW) == {}

    def test_a_rejected_plan_is_not_counted(self, authority_on, db_session_factory):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        goal_repository.set_plan_status(support.PLAN_ID, "rejected")
        assert autonomy_engine._collect_plan_facts(USER, NOW) == {}

    def test_a_finished_goal_leaves_no_facts(self, authority_on, db_session_factory):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        goal_repository.finish_goal(goal.id, "completed")
        assert autonomy_engine._collect_plan_facts(USER, NOW) == {}


class TestDegradation:
    """U6 / §6.5：装配失败降级为空包，不抛出、不阻塞 tick。"""

    def test_read_failure_degrades_to_empty(self, authority_on, monkeypatch):
        monkeypatch.setattr(goal_repository, "list_active_plans", _plans_down)
        assert autonomy_engine._collect_plan_facts(USER, NOW) == {}

    def test_scheduler_defect_degrades_to_empty(
        self, authority_on, db_session_factory, monkeypatch
    ):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)

        def _boom(*_args, **_kwargs):
            raise ValueError("scheduler defect")

        monkeypatch.setattr(
            autonomy_engine.plan_scheduler.PlanScheduler, "current_step", _boom
        )
        assert autonomy_engine._collect_plan_facts(USER, NOW) == {}

    def test_surface_failure_only_disables_the_off_surface_dimension(
        self, authority_on, db_session_factory, monkeypatch
    ):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("registry down")

        monkeypatch.setattr(autonomy_engine, "resolve_autonomy_surface", _boom)
        facts = autonomy_engine._collect_plan_facts(USER, NOW)
        assert facts["blocked_steps"] == 0
        assert facts["current_step"] == 1

    def test_snapshot_assembly_survives_a_failed_packet(
        self, authority_on, db_session_factory, monkeypatch
    ):
        """**不阻塞 tick**：装配点抛错时快照仍建成、策略仍给出裁决。"""
        monkeypatch.setattr(goal_repository, "list_active_plans", _plans_down)
        snapshot = autonomy_engine._snapshot_for(USER, "plan7-s1", NOW, NOW)
        assert snapshot.plan_facts == {}
        verdict = autonomy_policy.evaluate(
            support.signal(), snapshot, get_settings(), NOW
        )
        assert verdict.decision in ("act", "wait", "ignore")


class TestGatingAndParity:
    """I10 / I11 / D1 / D8 语义反转（v25 去门控）：采集恒发生，「空包零额外读取」由
    「无 active 计划 → 空包」承担；原子闸 off 三用例随开关退役，空包语义用例保留。"""

    def test_empty_packet_keeps_the_v24_verdict_bytes(self):
        baseline = autonomy_policy.evaluate(
            support.signal(), support.act_snapshot(), None, NOW
        )
        with_empty = autonomy_policy.evaluate(
            support.signal(), support.act_snapshot(plan_facts={}), None, NOW
        )
        assert baseline.model_dump() == with_empty.model_dump()

    def test_empty_packet_is_returned_untouched_by_the_modulation(self):
        baseline = autonomy_policy.evaluate(
            support.signal(), support.act_snapshot(), None, NOW
        )
        assert (
            autonomy_policy._apply_plan_adjustments(
                baseline, autonomy_policy.PolicySnapshot()
            )
            is baseline
        )


class TestBoundedByTheExistingBudget:
    """§4.2.1 有界：整体经既有 `observability.bound_extra` 裁剪（不新增预算机制）。"""

    def test_packet_is_clipped_by_the_existing_char_budget(
        self, authority_on, db_session_factory, override_settings
    ):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        override_settings(observability_step_extra_max_chars=30)
        facts = autonomy_engine._collect_plan_facts(USER, NOW)
        assert list(facts) == ["truncated_summary"]

    def test_packet_is_json_serializable(self, authority_on, db_session_factory):
        import json

        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        facts = autonomy_engine._collect_plan_facts(USER, NOW)
        assert json.loads(json.dumps(facts)) == facts


class TestDecisionAuditCarriesThePacket:
    """§7 写入面：`plan_facts` 只进既有 `decision_records.input_snapshot`（零新列）。"""

    def test_audit_row_carries_the_packet_only_when_present(self):
        verdict = autonomy_policy.AutonomyVerdict(
            decision="act", reason="触发", trigger=support.signal()
        )
        without = autonomy_engine._decision_record(
            verdict=verdict,
            signal=support.signal(),
            snapshot=support.act_snapshot(),
            user_id=USER,
            session_id=support.SESSION_ID,
        )
        assert "plan_facts" not in without.input_snapshot
        with_facts = autonomy_engine._decision_record(
            verdict=verdict,
            signal=support.signal(),
            snapshot=support.barrier_snapshot(),
            user_id=USER,
            session_id=support.SESSION_ID,
        )
        assert with_facts.input_snapshot["plan_facts"] == support.plan_facts()

    def test_audit_row_kind_is_an_existing_value(self):
        verdict = autonomy_policy.AutonomyVerdict(
            decision="act", reason="触发", trigger=support.signal()
        )
        record = autonomy_engine._decision_record(
            verdict=verdict,
            signal=support.signal(),
            snapshot=support.barrier_snapshot(),
            user_id=USER,
            session_id=support.SESSION_ID,
        )
        assert record.kind.value == "proactive_autonomy"


class TestAssemblyIsReadOnly:
    """I7 / D6：装配全程只读（`goal_repository` 只读接口 + 纯函数 + 审计只读）。"""

    def test_only_read_entries_are_consumed(self, authority_on, db_session_factory):
        goal = support.seed_layered_goal(USER)
        support.seed_plan(goal.id)
        before = len(goal_repository.list_plans(goal.id))
        support.seed_advance(goal.id)
        decisions_before = len(
            decision_repository.search(user_id=USER, limit=200)
        )

        autonomy_engine._collect_plan_facts(USER, NOW)

        assert len(goal_repository.list_plans(goal.id)) == before
        assert (
            len(decision_repository.search(user_id=USER, limit=200))
            == decisions_before
        )

    def test_the_plan_row_is_untouched(self, authority_on, db_session_factory):
        goal = support.seed_layered_goal(USER)
        created = support.seed_plan(goal.id)
        autonomy_engine._collect_plan_facts(USER, NOW)
        reloaded = goal_repository.get_plan(created.id)
        assert reloaded is not None
        assert reloaded.model_dump() == created.model_dump()

    def test_sub_goal_specs_are_not_mutated(self, authority_on, db_session_factory):
        goal = support.seed_layered_goal(USER)
        steps: list[SubGoalSpec] = [support.spec(1), support.spec(2, depends_on=[1])]
        created = support.seed_plan(goal.id, steps)
        plan = support.plan(steps, plan_id=created.id)
        before = [spec.model_dump() for spec in plan.sub_goals]
        autonomy_engine._collect_plan_facts(USER, NOW)
        assert [spec.model_dump() for spec in plan.sub_goals] == before
