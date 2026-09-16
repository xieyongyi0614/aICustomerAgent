"""PLAN-004 粒度断言：L1~L4 四级映射可举证 + L2 三条粒度判据（G1 / G2 / G3）通过用例与反例。

覆盖 Task Detail §9.1 的 U14 与 §8 Step 5：粒度裁决（architecture.md §3.5）落地为**可判定**的
判据，而非只写在文档里。`_task_granularity` 是举证工具，**不是拒绝闸**——拒绝由
`PlanValidator` 三闸裁决（`test_plan004_validator.py`）。
"""

from app.character.asuna.action import ACTION_TOOL_MAP
from app.models.action import ACTION_TYPES
from app.models.goal import SubGoalSpec
from app.services.planning import decompose as decompose_mod

from .plan004_support import (
    REMINDER_CREATE,
    bind,
    bound_surface,
    decompose,
    make_ctx,
    parsed,
    plan004_binding_on,
    step,
)


class TestLevelMappingIsEvidenced:
    """R7：Goal → Task → Action → Tool 四级映射逐条可举证。"""

    def test_four_levels_are_declared_in_order(self):
        assert tuple(level[0] for level in decompose_mod.PLAN_LEVELS) == (
            "L1",
            "L2",
            "L3",
            "L4",
        )

    def test_each_level_names_its_unit_model_producer_and_consumer(self):
        by_level = {level[0]: level for level in decompose_mod.PLAN_LEVELS}
        assert by_level["L1"][1:3] == ("Goal", "GoalRecord")
        assert "goal_planning.materialize" in by_level["L1"][3]
        assert by_level["L2"][1] == "Task"
        assert by_level["L2"][2].startswith("PlanStepSpec")
        assert by_level["L2"][3] == "TaskDecomposer"
        assert by_level["L2"][4] == "PlanScheduler / PlanExecutorBridge"
        assert by_level["L3"][2] == "ActionIntent / ActionRecord"
        assert by_level["L3"][4] == "action_engine"
        assert by_level["L4"][2] == "ToolBinding / ToolExecution"
        assert by_level["L4"][3] == "ToolSelector"

    def test_step_spec_is_the_existing_sub_goal_spec(self):
        """零新建 Task 模型（§10.3）：L2 就是扩展后的 `SubGoalSpec`。"""
        assert decompose_mod.PlanStepSpec is SubGoalSpec

    def test_l4_identity_is_the_v2_4_0_tool_id(self):
        candidate_ids = {
            tool_id for tool_ids in ACTION_TOOL_MAP.values() for tool_id in tool_ids
        }
        result = decompose(step(1))
        assert result.steps[0].tool_id in candidate_ids
        assert result.bindings[0].binding.definition.id == result.steps[0].tool_id

    def test_l2_capability_is_the_action_type_vocabulary(self):
        result = decompose(step(1))
        assert result.steps[0].capability in ACTION_TYPES


class TestGranularityChecks:
    """U14：G1 / G2 / G3 各有通过用例与反例。"""

    def test_declared_codes_match_the_implementation(self):
        assert tuple(check[0] for check in decompose_mod.TASK_GRANULARITY_CHECKS) == (
            "G1",
            "G2",
            "G3",
        )

    def test_bound_step_with_criteria_is_a_task(self):
        result = decompose(step(1, criteria={"type": "action_succeeded", "capability": "create_reminder"}))
        assert (
            decompose_mod._task_granularity(
                result.steps[0], result.steps, bound_surface()
            )
            == ()
        )

    def test_step_without_criteria_is_not_a_task(self):
        """G1 反例：判据为空 → 不构成 Task（`criteria` 空对象经 ③ 不报错，但粒度不成立）。"""
        bare = SubGoalSpec.model_validate(
            {
                "index": 1,
                "description": "无判据步骤",
                "capability": "create_reminder",
                "params": {},
                "criteria": {},
                "tool_id": REMINDER_CREATE,
            }
        )
        assert decompose_mod._task_granularity(bare, [bare], bound_surface()) == ("G1",)

    def test_unbound_step_without_a_fallback_is_not_executable(self):
        """G2 反例：绑定失败且无降级路径 → 不构成可执行 Task。"""
        result = decompose(step(1), ctx=make_ctx(REMINDER_CREATE))
        unbound = result.steps[0].model_copy(update={"tool_id": None})
        assert decompose_mod._task_granularity(unbound, [unbound], bound_surface())[0] == "G2"

    def test_step_requiring_branching_is_split_into_multiple_tasks(self):
        """G3 反例：需要分支 / 循环控制流的步骤（父步容器）不应作为一步执行。"""
        work, _bindings, _errors = bind(
            parsed(step(1), step(2, parent_index=1), step(3, parent_index=1))
        )
        parent = work[0].model_copy(update={"kind": "composite"})
        children = [
            spec.model_copy(update={"kind": "tool", "tool_id": REMINDER_CREATE})
            for spec in work[1:]
        ]
        forked = [parent, *children]
        assert decompose_mod._task_granularity(parent, forked, bound_surface()) == ("G3",)
        assert decompose_mod._task_granularity(children[0], forked, bound_surface()) == ()

    def test_granularity_verdict_is_deterministic(self):
        single = parsed(step(1))
        first = decompose_mod._task_granularity(single[0], single, bound_surface())
        second = decompose_mod._task_granularity(single[0], single, bound_surface())
        assert first == second
