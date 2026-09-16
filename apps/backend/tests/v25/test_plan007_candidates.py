"""PLAN-007 Step 4：计划推进意图经**既有 `goal_compile` 候选面**进入决策管线。

覆盖 Task Detail §9.2 I3 / I4 / I5 与 §4.2.3 契约表。

**`decision_pipeline.py` 零改动**的可执行形式：六维权重、`_SOURCE_PRIORITY` 表与
`_ACTION_SOURCES` 元组逐条冻结，且模块内**零计划感知**（代码口径无 `plan` 标识、
零规划模块导入）——计划态一律经既有 `goal_compile` 面进入，不新增候选源。
"""

from datetime import timedelta

import pytest

from app.services import decision_pipeline, goal_stack
from app.services.planning import goal_contract

from . import _plan_scan as scan
from . import plan007_support as support

USER = support.USER
NOW = support.NOW

FROZEN_DIMENSION_WEIGHTS = {
    "goal_alignment": 0.35,
    "state_fit": 0.15,
    "relationship_fit": 0.15,
    "timing": 0.15,
    "interest": 0.10,
    "cost": 0.10,
}

FROZEN_SOURCE_PRIORITY = {
    "user_directive": 0,
    "commitment_delivery": 1,
    "autonomy_trigger": 2,
    "goal_compile": 2,
    "turn_intention": 2,
    "capability": 3,
    "world_affordance": 3,
    "chat_response": 0,
    "silence": 4,
}

FROZEN_CANDIDATE_SOURCES = frozenset(FROZEN_SOURCE_PRIORITY)

PLAN_AWARE_MODULES = ("app.services.planning",)


@pytest.fixture
def stack_on(override_settings):
    """`v21_goal_stack_enabled` 开启（`goal_compile` 候选面的唯一来源，非本任务新增 Flag）。"""
    override_settings(v21_goal_stack_enabled="true", world_enabled="false")
    return True


class TestFrozenPipelineMath:
    """I3：六维权重与 `_SOURCE_PRIORITY` 快照对照零差异。"""

    def test_dimension_weights_are_unchanged(self):
        assert decision_pipeline._DIMENSION_WEIGHTS == FROZEN_DIMENSION_WEIGHTS
        assert sum(decision_pipeline._DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)

    def test_source_priority_table_is_unchanged(self):
        assert decision_pipeline._SOURCE_PRIORITY == FROZEN_SOURCE_PRIORITY
        assert decision_pipeline._SOURCE_PRIORITY["goal_compile"] == decision_pipeline.P2

    def test_priority_labels_are_unchanged(self):
        assert decision_pipeline.PRIORITY_LABELS == {
            0: "P0",
            1: "P1",
            2: "P2",
            3: "P3",
            4: "P4",
        }

    def test_action_sources_tuple_is_unchanged(self):
        assert decision_pipeline._ACTION_SOURCES == (
            "autonomy_trigger",
            "goal_compile",
            "turn_intention",
        )

    def test_pipeline_has_exactly_five_stages(self):
        """五段管线（候选 → 优先级 → 六维 → 四闸 → 选择）未增减环节。"""
        verdict = decision_pipeline.run_pipeline(
            stack=None, snapshot=None, trigger_intention="check_in", now=NOW
        )
        assert isinstance(verdict, decision_pipeline.DecisionResult)
        assert verdict.winner is not None
        assert set(verdict.audit) == {"candidates"}
        assert set(verdict.audit["candidates"][0]) >= {
            "source",
            "intention",
            "goal_id",
            "priority",
            "scores",
            "total",
            "gates",
            "won",
        }


class TestNoNewCandidateSource:
    """I4 / §4.2.3 禁止项：未新增 `Candidate.source` 值 / `_SOURCE_PRIORITY` 条目。"""

    def test_table_holds_exactly_the_nine_frozen_entries(self):
        assert len(decision_pipeline._SOURCE_PRIORITY) == 9
        assert set(decision_pipeline._SOURCE_PRIORITY) == FROZEN_CANDIDATE_SOURCES

    def test_collect_candidates_only_emits_frozen_sources(self):
        stack = goal_stack.GoalStack()
        candidates = decision_pipeline.collect_candidates(
            stack=stack,
            trigger_intention="check_in",
            trigger_goal_id=support.GOAL_ID,
            capabilities=["builtin.reminder.create"],
            chat_response=True,
            chat_response_intention="answer",
            chat_response_goal_id=None,
            world_impacts=[{"goal_opportunity": {"type": "user_care"}}],
        )
        emitted = {candidate.source for candidate in candidates}
        assert emitted <= FROZEN_CANDIDATE_SOURCES
        assert emitted == {
            "chat_response",
            "autonomy_trigger",
            "capability",
            "world_affordance",
            "silence",
        }

    def test_the_module_is_unaware_of_planning(self):
        """**零改动**的可执行形式：代码口径无计划标识、零规划模块导入。"""
        path = _pipeline_path()
        text = scan.code_text(path)
        assert "plan" not in text.lower()
        assert "PLAN_" not in text
        imported = scan.imported_modules(path)
        assert not [
            module
            for module in imported
            if module.startswith(PLAN_AWARE_MODULES)
        ]

    def test_the_planning_package_does_not_import_the_pipeline(self):
        """反向也零依赖：计划层不得消费决策管线（职责不交叉）。"""
        assert "app.services.decision_pipeline" not in scan.imported_modules(
            scan.PLANNING_PACKAGE_DIR / "goal_contract.py"
        )
        assert "app.services.decision_pipeline" not in scan.imported_modules(
            scan.PLANNING_PACKAGE_DIR / "observer.py"
        )


class TestPlanIntentionEntersTheGoalCompileFace:
    """I5 / §7.3 接线 2：计划推进意图经 `goal_compile` 面进入，优先级 P2 原样保留。"""

    @staticmethod
    def _stack_with_a_planned_goal():
        goal = support.seed_layered_goal(
            USER, layer="short_term", domain="personal", description="准备面试"
        )
        plan = support.seed_plan(
            goal.id, [support.spec(1, capability=support.REMINDER_ACTION)]
        )
        stack = goal_stack.evaluate_stack(USER, NOW, retire_overdue_enabled=False)
        return goal, plan, stack

    def test_the_planned_goal_reaches_the_stack(self, stack_on, db_session_factory):
        goal, plan, stack = self._stack_with_a_planned_goal()
        assert stack.primary() is not None
        assert stack.primary().id == goal.id
        assert goal_repository_active_plans(USER) == [(goal.id, plan.version)]

    def test_a_goal_compile_candidate_is_emitted_for_the_planned_goal(
        self, stack_on, db_session_factory
    ):
        goal, _plan, stack = self._stack_with_a_planned_goal()
        candidates = decision_pipeline.collect_candidates(stack=stack)
        compiled = [c for c in candidates if c.source == "goal_compile"]
        assert len(compiled) == 1
        assert compiled[0].goal_id == goal.id
        assert compiled[0].payload["type"] == goal.type

    def test_the_compiled_candidate_keeps_priority_p2(
        self, stack_on, db_session_factory
    ):
        _goal, _plan, stack = self._stack_with_a_planned_goal()
        candidates = decision_pipeline.collect_candidates(
            stack=stack,
            trigger_intention=support.CHECK_IN_INTENTION,
            trigger_goal_id=support.GOAL_ID,
        )
        decision_pipeline.assign_priorities(candidates)
        by_source = {candidate.source: candidate for candidate in candidates}
        assert by_source["goal_compile"].priority == decision_pipeline.P2
        assert decision_pipeline.PRIORITY_LABELS[by_source["goal_compile"].priority] == "P2"
        assert by_source["autonomy_trigger"].priority == decision_pipeline.P2

    def test_both_intentions_compete_on_the_same_score_sheet(
        self, stack_on, db_session_factory
    ):
        """「该做下一步了」与「要不要主动」同表竞争：一行候选各自成账、六维各有一分。"""
        from app.core.settings import get_settings

        _goal, _plan, stack = self._stack_with_a_planned_goal()
        result = decision_pipeline.run_pipeline(
            stack=stack,
            snapshot=None,
            trigger_intention=support.CHECK_IN_INTENTION,
            trigger_goal_id=support.GOAL_ID,
            now=NOW,
        )
        audit = {item["source"]: item for item in result.audit["candidates"]}
        assert "goal_compile" in audit and "autonomy_trigger" in audit
        assert audit["goal_compile"]["priority"] == "P2"
        assert set(audit["goal_compile"]["scores"]) == set(FROZEN_DIMENSION_WEIGHTS)
        weighted = sum(
            audit["goal_compile"]["scores"][name] * weight
            for name, weight in FROZEN_DIMENSION_WEIGHTS.items()
        )
        assert audit["goal_compile"]["total"] == round(
            min(max(weighted * get_settings().v21_decision_weight, 0.0), 1.0), 4
        )

    def test_the_compiled_intention_is_resolved_by_the_existing_defaults(
        self, stack_on, db_session_factory
    ):
        """候选意图仍由既有 `INTENTION_GOAL_DEFAULTS` / FIT 解析（零新增意图逻辑）。"""
        goal, _plan, stack = self._stack_with_a_planned_goal()
        candidates = decision_pipeline.collect_candidates(stack=stack)
        compiled = next(c for c in candidates if c.source == "goal_compile")
        intention = decision_pipeline._intention_for(compiled, stack)
        assert intention is not None
        from app.models.intention import INTENTION_GOAL_DEFAULTS

        assert intention == INTENTION_GOAL_DEFAULTS[goal.type]

    def test_the_plan_state_itself_adds_no_candidate(self, stack_on, db_session_factory):
        """计划态不新增候选：同目标有无计划，`goal_compile` 候选数量一致。"""
        goal = support.seed_layered_goal(
            USER, layer="short_term", domain="personal", description="无计划目标"
        )
        stack = goal_stack.evaluate_stack(USER, NOW, retire_overdue_enabled=False)
        without_plan = decision_pipeline.collect_candidates(stack=stack)
        support.seed_plan(
            goal.id, [support.spec(1, capability=support.REMINDER_ACTION)]
        )
        stack_with_plan = goal_stack.evaluate_stack(USER, NOW, retire_overdue_enabled=False)
        with_plan = decision_pipeline.collect_candidates(stack=stack_with_plan)
        assert len(with_plan) == len(without_plan)
        assert sum(c.source == "goal_compile" for c in with_plan) == 1


def goal_repository_active_plans(user_id: str) -> list[tuple[str, int]]:
    """用户身上 active 计划的最小投影（`(goal_id, version)`，供候选面用例对照）。"""
    from app.repositories import goal_repository

    return [
        (goal.id, plan.version)
        for goal, plan in goal_repository.list_active_plans(user_id)
    ]


def _pipeline_path():
    from pathlib import Path

    return Path(decision_pipeline.__file__)


def test_goal_contract_still_holds_the_frozen_read_face():
    """PLAN-001 冻结的计划只读面未被本任务触碰（候选面不新增读取入口）。"""
    assert goal_contract.PLANNING_ADVANCE_CANDIDATE_GATE == (
        "app.repositories.goal_repository",
        "list_active_plans",
    )
    assert (
        "app.repositories.goal_repository",
        "list_active_plans",
    ) in goal_contract.PLANNING_READ_INTERFACES


def test_module_level_imports_stay_free_of_planning():
    assert not [
        module
        for module in scan.imported_modules(_pipeline_path())
        if module.startswith(PLAN_AWARE_MODULES)
    ]


def test_plan_facts_never_reach_the_pipeline():
    """管线输入面不含计划事实：`run_pipeline` 的形参集未扩。"""
    import inspect

    parameters = set(inspect.signature(decision_pipeline.run_pipeline).parameters)
    assert parameters == {
        "stack",
        "snapshot",
        "trigger_intention",
        "trigger_goal_id",
        "capabilities",
        "chat_response",
        "chat_response_intention",
        "chat_response_goal_id",
        "run",
        "now",
        "world_impacts",
        "world_schedule",
        "tool_insights",
    }
    assert not [name for name in parameters if "plan" in name]


def test_the_snapshot_field_is_not_consumed_as_a_plan_channel():
    """`score_candidates` 只读既有快照维度，不读 `plan_facts`（禁令的可执行形式）。"""
    from app.application.agent_state_context import AgentStateSnapshot

    assert "plan_facts" not in AgentStateSnapshot.model_fields
