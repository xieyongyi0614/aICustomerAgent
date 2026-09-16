"""PLAN-009 Step 1：判据 A（计划本体是否落 `goal_plans`）——三条条件 + 五类场景裁决。

覆盖 Task Detail §9.1 U1 / U2、§9.3 S8 的判据面；对应 §8 Step 1 与 §4.2.1 / §6.1。

与 Task Detail §8 Step 1.3 的接入点确认（实现留痕，可执行）

> 判据 A 以**纯判据资产**交付，**不新增闸**。`PlanningEngine` 的七道闸与
> `goal_repository.create_plan` 调用点是 PLAN-003 的既有链路，单步计划在
> `tests/v25/test_plan003_engine.py::test_...` 中就被断言会落库（PLAN-003 既有行为），
> 在 `_persist` 前插入判据 A 会改变 PLAN-003 / PLAN-005 的既有行为并击穿全部既有单步用例，
> 违反零回归纪律。故 §9.3 S8 的「两侧」以**判据裁决**（本模块的五类场景表 + 本文件的
> 零调用点断言）兑现，接入点留待后续任务按需评估。
"""

import pytest

from app.services.planning import engine as engine_mod
from app.services.planning import memory_policy as plan_memory_policy

from . import plan009_support as support

MODULE_PATH = support.module_path("memory_policy.py")

PURE_FORBIDDEN_CALLS = (
    "get_settings",
    "SessionLocal",
    "apply_policy",
    "ingest_from_goal_completion",
    "should_persist_plan",
)


def _verdict(**overrides) -> bool:
    payload = {
        "step_count": 2,
        "cross_tick": True,
        "every_step_has_criteria": True,
        "needs_idempotency_or_recovery": True,
    }
    payload.update(overrides)
    return plan_memory_policy.should_persist_plan(**payload)


class TestCriterionAThreeConditions:
    """U1：三条条件各自一通过 / 一不通过；三条件全满足才 `True`。"""

    def test_all_three_conditions_satisfied_returns_true(self):
        assert _verdict() is True

    @pytest.mark.parametrize(
        "overrides",
        (
            {"step_count": 2, "cross_tick": False},
            {"step_count": 1, "cross_tick": True},
        ),
    )
    def test_criterion_a1_passes_by_either_step_count_or_cross_tick(self, overrides):
        assert _verdict(**overrides) is True

    def test_criterion_a1_fails_for_a_single_step_without_cross_tick(self):
        assert _verdict(step_count=1, cross_tick=False) is False

    def test_criterion_a2_fails_without_per_step_criteria(self):
        assert _verdict(every_step_has_criteria=False) is False

    def test_criterion_a3_fails_without_idempotency_or_recovery_need(self):
        assert _verdict(needs_idempotency_or_recovery=False) is False

    @pytest.mark.parametrize(
        "overrides",
        (
            {"step_count": 1, "cross_tick": False},
            {"every_step_has_criteria": False},
            {"needs_idempotency_or_recovery": False},
        ),
    )
    def test_any_single_missing_condition_is_enough_to_decline(self, overrides):
        assert _verdict(**overrides) is False


class TestCriterionAFiveScenarios:
    """U2：五类场景与 §4.2.1 裁决表逐条一致。"""

    @pytest.mark.parametrize(
        "label,inputs,expected",
        support.PERSIST_SCENARIOS,
        ids=[item[0] for item in support.PERSIST_SCENARIOS],
    )
    def test_scenario_verdict_matches_the_doc_table(self, label, inputs, expected):
        assert plan_memory_policy.should_persist_plan(**inputs) is expected

    def test_scenarios_cover_both_sides_of_the_verdict(self):
        assert {expected for _, _, expected in support.PERSIST_SCENARIOS} == {True, False}

    def test_single_step_cross_day_confirmation_does_not_land_a_plan(self):
        """§4.2.1 第三行（§10.1 点名的边界场景）：单步但需跨天确认送达 → 不落计划。"""
        inputs = dict(support.PERSIST_SCENARIOS[2][1])
        assert inputs["step_count"] == 1
        assert inputs["cross_tick"] is True
        assert plan_memory_policy.should_persist_plan(**inputs) is False


class TestCriterionAPurity:
    """U11 半边：判据 A 零 IO / 零 LLM / 零设置直调（纯合取）。"""

    def test_should_persist_plan_calls_no_io_surface(self):
        calls = support.function_call_names(MODULE_PATH, "should_persist_plan")
        assert calls & set(PURE_FORBIDDEN_CALLS) == set()

    def test_threshold_comes_from_the_module_constant(self):
        assert plan_memory_policy.PLAN_PERSIST_MIN_STEPS == 2
        assert _verdict(step_count=2, cross_tick=False) is True
        assert _verdict(step_count=1, cross_tick=False) is False


class TestCriterionAStaysAPredicate:
    """§8 Step 1.3：本任务不新增闸——判据 A 在生产代码中零调用点。"""

    def test_should_persist_plan_has_no_production_call_site(self):
        declaration_only = {"memory_policy.py", "__init__.py"}
        offenders = {
            path.name: "should_persist_plan"
            for path in support.plan_modules()
            if path.name not in declaration_only
            and "should_persist_plan" in path.read_text(encoding="utf-8")
        }
        assert offenders == {}
        source = MODULE_PATH.read_text(encoding="utf-8")
        assert source.count("should_persist_plan(") == 1

    def test_planning_engine_seven_gates_and_write_face_are_untouched(self):
        """PLAN-003 既有链路未被本任务插闸：七道闸理由码与唯一写面调用点仍在位。"""
        assert engine_mod.REASON_TOOL_UNRESOLVABLE == "plan_tool_unresolvable"
        assert engine_mod.REASON_TOOL_OFF_SURFACE == "plan_tool_off_surface"
        source = (support.module_path("engine.py")).read_text(encoding="utf-8")
        assert "goal_repository.create_plan(" in source
        assert "should_persist_plan" not in source
