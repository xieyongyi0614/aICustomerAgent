"""PLAN-009 Step 2：判据 B（`PlanMemoryPolicy` 边界表）——七行逐条 + G-MEMORY + 常数复用。

覆盖 Task Detail §9.1 U3 / U10 / U11 / U12 / U13；对应 §8 Step 2 与 §4.2.2 / §6.2。
"""

import pytest

from app.core.settings import get_settings
from app.services.planning import memory_policy as plan_memory_policy
from app.services.tool import memory_policy as tool_memory_policy

from . import plan009_support as support

MODULE_PATH = support.module_path("memory_policy.py")

POLICY = plan_memory_policy.PlanMemoryPolicy()

DEPOSIT_EVENTS = (
    plan_memory_policy.EVENT_PLAN_COMPLETED,
    plan_memory_policy.EVENT_PLAN_FAILED,
    plan_memory_policy.EVENT_PLAN_ABANDONED,
)

DECLINE_EVENTS = (
    plan_memory_policy.EVENT_PLAN_CREATED,
    plan_memory_policy.EVENT_PLAN_REVISED,
    plan_memory_policy.EVENT_STEP_SUCCEEDED,
    plan_memory_policy.EVENT_STEP_FAILED,
)

TOOL_SIDE_CONSTANTS = (
    "MEMORY_CONTENT_MAX_CHARS",
    "DEFAULT_MEMORY_TYPE",
    "DEFAULT_IMPORTANCE",
    "DEFAULT_SOURCE",
    "DEFAULT_CONFIDENCE",
    "FAILED_IMPORTANCE_FLOOR",
    "REASON_POLICY_DEPOSIT",
    "REASON_POLICY_DECLINED",
    "REASON_NO_POLICY_ROW",
)


class TestBoundaryTableSevenRows:
    """U3：七行 `event_kind` × deposit 逐条；✅ 三行有沉积字段，❌ 四行一律为空。"""

    def test_event_kind_value_set_is_exactly_seven_values(self):
        assert plan_memory_policy.PLAN_MEMORY_EVENT_KINDS == (
            "plan_completed",
            "plan_failed",
            "plan_abandoned",
            "plan_created",
            "plan_revised",
            "step_succeeded",
            "step_failed",
        )
        assert set(plan_memory_policy.PLAN_MEMORY_BOUNDARY_TABLE) == set(
            plan_memory_policy.PLAN_MEMORY_EVENT_KINDS
        )

    @pytest.mark.parametrize("event_kind", DEPOSIT_EVENTS)
    def test_deposit_rows_carry_the_full_deposit_configuration(self, event_kind):
        row = policy_row(event_kind)
        assert row["deposit"] is True
        assert row["memory_type"] == tool_memory_policy.DEFAULT_MEMORY_TYPE
        assert row["source"] == tool_memory_policy.DEFAULT_SOURCE
        assert isinstance(row["importance"], float)

    @pytest.mark.parametrize("event_kind", DECLINE_EVENTS)
    def test_declined_rows_carry_no_deposit_configuration(self, event_kind):
        row = policy_row(event_kind)
        assert row == {"deposit": False}
        decision = POLICY.decide(event_kind)
        assert decision.deposit is False
        assert (decision.memory_type, decision.importance, decision.source) == (
            None,
            None,
            None,
        )

    def test_plan_body_and_step_events_never_deposit(self):
        """§10.1 零写入断言：计划创建 / 修订 / 单步成功 / 单步失败四类事件的判定为 ❌。"""
        assert [POLICY.decide(event).deposit for event in DECLINE_EVENTS] == [False] * 4

    def test_unknown_event_kind_is_not_a_deposit(self):
        decision = POLICY.decide("plan_something_else")
        assert decision.deposit is False
        assert decision.reason == tool_memory_policy.REASON_NO_POLICY_ROW
        assert POLICY.row_for("plan_something_else") is None

    def test_decision_reasons_reuse_the_tool_side_vocabulary(self):
        for event_kind in DEPOSIT_EVENTS:
            assert POLICY.decide(event_kind).reason == tool_memory_policy.REASON_POLICY_DEPOSIT
        for event_kind in DECLINE_EVENTS:
            assert (
                POLICY.decide(event_kind).reason == tool_memory_policy.REASON_POLICY_DECLINED
            )

    def test_template_key_is_the_event_kind(self):
        for event_kind in DEPOSIT_EVENTS:
            assert POLICY.decide(event_kind).template_key == event_kind


class TestGMemorySourceDiscipline:
    """U13 / D3：三类终态 `source` 恒 `user_derived`，`importance` 受 floor 约束（G-MEMORY）。"""

    @pytest.mark.parametrize("event_kind", DEPOSIT_EVENTS)
    def test_source_is_never_ai_inferred(self, event_kind):
        decision = POLICY.decide(event_kind)
        assert decision.source == "user_derived"
        assert decision.source == tool_memory_policy.DEFAULT_SOURCE
        assert "ai_inferred" not in {
            str(row.get("source")) for row in plan_memory_policy.PLAN_MEMORY_BOUNDARY_TABLE.values()
        }

    def test_completed_importance_matches_the_doc_table(self):
        assert POLICY.decide(
            plan_memory_policy.EVENT_PLAN_COMPLETED
        ).importance == plan_memory_policy.PLAN_COMPLETED_IMPORTANCE == 0.7

    @pytest.mark.parametrize(
        "event_kind",
        (plan_memory_policy.EVENT_PLAN_FAILED, plan_memory_policy.EVENT_PLAN_ABANDONED),
    )
    def test_failed_and_abandoned_respect_the_configured_floor(self, event_kind):
        floor = get_settings().plan_memory_importance_floor
        assert POLICY.decide(event_kind).importance >= floor

    @pytest.mark.parametrize(
        "event_kind",
        (plan_memory_policy.EVENT_PLAN_FAILED, plan_memory_policy.EVENT_PLAN_ABANDONED),
    )
    def test_a_raised_floor_lifts_the_importance(self, event_kind, override_settings):
        override_settings(plan_memory_importance_floor="0.85")
        assert POLICY.decide(event_kind).importance == 0.85

    def test_an_ai_inferred_row_is_a_hard_implementation_defect(self):
        """G-MEMORY 的**配置面**防线：把 `ai_inferred` 写进边界表即 fail-fast，不静默降级。"""
        policy = plan_memory_policy.PlanMemoryPolicy(
            rows={"plan_completed": {"deposit": True, "source": "ai_inferred", "importance": 0.7}}
        )
        with pytest.raises(ValueError, match="ai_inferred"):
            policy.decide("plan_completed")


class TestPureFunctionDiscipline:
    """U11：`PlanMemoryPolicy` 纯函数——零 IO、零 LLM、零仓储触达。"""

    def test_decide_touches_no_repository_policy_or_ingest_surface(self, monkeypatch):
        from app.repositories import action_repository, memory_repository
        from app.services.memory import policy as policy_gate
        from app.services.memory import ingest as ingest_mod

        def _boom(*args, **kwargs):
            raise AssertionError("判据 B 不得触达 IO 面")

        for module, name in (
            (memory_repository, "create_memory"),
            (memory_repository, "list_active"),
            (action_repository, "list_records"),
            (action_repository, "save_record"),
            (policy_gate, "apply_policy"),
            (ingest_mod, "ingest_from_goal_completion"),
        ):
            monkeypatch.setattr(module, name, _boom)

        for event_kind in plan_memory_policy.PLAN_MEMORY_EVENT_KINDS:
            decision = POLICY.decide(event_kind, settings=get_settings())
            assert isinstance(decision, plan_memory_policy.PlanMemoryDecision)

    def test_decide_never_calls_get_settings_when_settings_are_injected(self, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            plan_memory_policy,
            "get_settings",
            lambda: calls.append("get_settings") or get_settings(),
        )
        POLICY.decide(plan_memory_policy.EVENT_PLAN_COMPLETED, settings=get_settings())
        assert calls == []

    def test_policy_object_holds_no_mutable_state(self):
        first = POLICY.row_for(plan_memory_policy.EVENT_PLAN_COMPLETED)
        first["deposit"] = False
        assert POLICY.decide(plan_memory_policy.EVENT_PLAN_COMPLETED).deposit is True


class TestShapeAlignment:
    """U12 / D2：与 `services/tool/memory_policy.py` 的边界表 + 决策同构。"""

    def test_decision_field_set_matches_the_tool_side_decision(self):
        plan_fields = tuple(plan_memory_policy.PlanMemoryDecision.__dataclass_fields__)
        tool_fields = tuple(tool_memory_policy.MemoryDecision.__dataclass_fields__)
        assert plan_fields == tool_fields

    def test_both_policies_expose_row_for_and_a_classifier(self):
        tool_policy = tool_memory_policy.get_tool_memory_policy()
        assert hasattr(tool_policy, "row_for")
        assert hasattr(plan_memory_policy.get_plan_memory_policy(), "row_for")
        assert callable(plan_memory_policy.get_plan_memory_policy().decide)
        assert callable(tool_policy.classify)

    def test_boundary_rows_are_plain_dicts_like_the_tool_side_table(self):
        table = plan_memory_policy.PLAN_MEMORY_BOUNDARY_TABLE
        assert all(isinstance(key, str) and isinstance(row, dict) for key, row in table.items())
        assert all(
            isinstance(key, str) and isinstance(row, dict)
            for key, row in tool_memory_policy.BOUNDARY_TABLE.items()
        )

    def test_declined_rows_do_not_claim_a_deposit_field(self):
        """❌ 四行连 `deposit=True` 都不带（工具侧同款写法：只写 `{"deposit": False}`）。"""
        assert all(
            row == {"deposit": False}
            for row in (
                plan_memory_policy.PLAN_MEMORY_BOUNDARY_TABLE[event]
                for event in DECLINE_EVENTS
            )
        )


class TestConstantReuse:
    """U10 / D4：常量复用既有取值，零新造（静态）。"""

    @pytest.mark.parametrize("name", TOOL_SIDE_CONSTANTS)
    def test_reused_constants_are_imported_not_redefined(self, name):
        assert name not in support.assigned_names(MODULE_PATH)

    @pytest.mark.parametrize("name", TOOL_SIDE_CONSTANTS)
    def test_reused_constants_are_identical_objects(self, name):
        assert getattr(plan_memory_policy, name) is getattr(tool_memory_policy, name)

    def test_no_duplicated_numeric_constant_literals(self):
        numbers = set(support.module_numbers(MODULE_PATH))
        assert numbers & {
            float(tool_memory_policy.MEMORY_CONTENT_MAX_CHARS),
            float(tool_memory_policy.FAILED_IMPORTANCE_FLOOR),
            float(tool_memory_policy.DEFAULT_CONFIDENCE),
            float(tool_memory_policy.DEFAULT_IMPORTANCE),
        } == set()

    def test_domain_values_come_from_the_imports_not_from_literals(self):
        literals = set(support.module_literals(MODULE_PATH))
        assert tool_memory_policy.DEFAULT_MEMORY_TYPE not in literals
        assert tool_memory_policy.DEFAULT_SOURCE not in literals


def policy_row(event_kind: str) -> dict:
    row = POLICY.row_for(event_kind)
    assert row is not None
    return row
