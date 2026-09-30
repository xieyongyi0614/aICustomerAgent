"""PLAN-007 Step 6：G-BOUNDARY 输出契约断言（静态 + 运行时）。

覆盖 Task Detail §6.4 B1~B4 与 §4.2.2 分工对照表的可执行部分。

| # | 断言 | 本模块的可执行形式 |
|---|---|---|
| B1 | Autonomy 只出 `AutonomyVerdict` + intention | 静态：自治路径零 `GoalPlanRecord` / `SubGoalSpec` 构造、零计划写调用 |
| B2 | Planning 只出 `GoalPlanRecord` + `PlanStepSpec[]` | 静态：计划包零 `AutonomyVerdict` / `ProactiveAction` / intention 构造 |
| B3 | Tool 只出 `ToolResult` | 静态：工具层零计划导入、零裁决构造 |
| B4 | 三者无交叉写面 | 写面矩阵：契约类型声明处两两不同；独占写表两两不相交（`decision_records` 按 `kind` 区分、`action_records` 经 Action 层唯一入口） |

运行时断言（§8 Step 6.3）：对一次「计划步骤 → Action」的链路各层取输出，断言类型**恰为**
各自契约类型；并断言自治路径跑完不写计划表、计划路径跑完不产 `ProactiveAction`。
"""

import ast
from datetime import timedelta
from pathlib import Path

from app.models.action import ActionIntent
from app.models.autonomy import AutonomyVerdict
from app.models.goal import GoalPlanRecord, SubGoalSpec
from app.models.observability import DecisionKind
from app.models.plan import PlanAdvance, PlanStepOutcome
from app.models.tool import ToolResult
from app.repositories import action_repository, goal_repository, proactive_repository
from app.engines import autonomy as autonomy_policy
from app.engines import decision as decision_pipeline
from app.services.planning.executor_bridge import PlanExecutorBridge
from app.services.planning.observer import PlanObserver, PlanSettlement
from app.services.planning.scheduler import PlanScheduler

from . import _plan_scan as scan
from . import plan007_support as support

USER = support.USER
NOW = support.NOW

AUTONOMY_MODULES = (
    "app/engines/autonomy.py",
    "app/application/autonomy_engine.py",
    "app/engines/decision.py",
    "app/services/autonomy/trigger.py",
)

TOOL_MODULES = (
    "app/services/tool/registry.py",
    "app/services/tool/surface.py",
    "app/services/tool/executor.py",
    "app/services/tool/normalizer.py",
)

PLAN_WRITE_CALLS = (
    "create_plan",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
)

PLAN_CONTRACT_TYPES = ("GoalPlanRecord", "SubGoalSpec", "PlanStepOutcome", "PlanAdvance")

AUTONOMY_CONTRACT_TYPES = ("AutonomyVerdict", "ProactiveAction")

AUTONOMY_DECISION_KIND = DecisionKind.PROACTIVE_AUTONOMY
PLANNING_DECISION_KIND = DecisionKind.GOAL_LIFECYCLE

EXCLUSIVE_WRITE_TABLES: dict[str, tuple[str, ...]] = {
    "autonomy": ("proactive_actions",),
    "planning": ("goal_plans",),
    "tool": ("world_events", "memories"),
}
"""三者各自**独占**的写表（两两不相交，由 `test_exclusive_write_tables_are_disjoint` 判定）。

`decision_records`（共享只增审计表，按 `kind` 区分）与 `action_records`（Action 层唯一
编排器入口，planning 经 `PlanExecutorBridge` 委托、autonomy 经 `_produce_autonomy_action`
委托）不在独占集内——这是 §6.4 B4 括注的既有事实，不是本任务引入的交叉面。
"""

SHARED_AUDIT_TABLE = "decision_records"
DELEGATED_ACTION_TABLE = "action_records"


def _backend_root() -> Path:
    return scan.REPO_ROOT


def _scan(*relative: str) -> list[Path]:
    return [_backend_root() / relative_path for relative_path in relative]


def _constructed_names(path: Path) -> set[str]:
    """模块内被**调用**的名字（构造 / 写函数调用的可判定形式）。"""
    names: set[str] = set()
    for node in ast.walk(scan.tree(path)):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _imported_modules(path: Path) -> set[str]:
    return scan.imported_modules(path)


class TestWriteFaceMatrix:
    """B4：写面矩阵的数据面与类型面。"""

    def test_exclusive_write_tables_are_disjoint(self):
        groups = [set(tables) for tables in EXCLUSIVE_WRITE_TABLES.values()]
        assert len(groups) == 3
        assert groups[0] & groups[1] == set()
        assert groups[0] & groups[2] == set()
        assert groups[1] & groups[2] == set()

    def test_the_shared_audit_table_is_discriminated_by_kind(self):
        assert SHARED_AUDIT_TABLE != DELEGATED_ACTION_TABLE
        assert AUTONOMY_DECISION_KIND != PLANNING_DECISION_KIND
        assert AUTONOMY_DECISION_KIND.value == "proactive_autonomy"
        assert PLANNING_DECISION_KIND.value == "goal_lifecycle"

    def test_contract_types_have_three_distinct_declaring_modules(self):
        owners = {
            AutonomyVerdict.__module__,
            GoalPlanRecord.__module__,
            ToolResult.__module__,
        }
        assert owners == {"app.models.autonomy", "app.models.goal", "app.models.tool"}
        assert SubGoalSpec.__module__ == "app.models.goal"

    def test_output_type_sets_are_pairwise_disjoint(self):
        autonomy_outputs = {AutonomyVerdict}
        planning_outputs = {GoalPlanRecord, SubGoalSpec, PlanStepOutcome, PlanAdvance}
        tool_outputs = {ToolResult}
        for left, right in (
            (autonomy_outputs, planning_outputs),
            (autonomy_outputs, tool_outputs),
            (planning_outputs, tool_outputs),
        ):
            assert left & right == set()


class TestBoundaryStaticAssertions:
    """B1 / B2 / B3：静态扫描（代码口径 + AST 口径）。"""

    def test_autonomy_never_constructs_or_writes_plan_contracts(self):
        for path in _scan(*AUTONOMY_MODULES):
            names = _constructed_names(path)
            assert names & set(PLAN_CONTRACT_TYPES) == set(), path.name
            assert names & set(PLAN_WRITE_CALLS) == set(), path.name

    def test_autonomy_only_reads_the_plan_scheduler(self):
        """自治侧只许读 `planning.scheduler`（纯函数），不得触达引擎 / 拆解 / 执行 / 修订。"""
        forbidden = (
            "app.services.planning.engine",
            "app.services.planning.decompose",
            "app.services.planning.executor_bridge",
            "app.services.planning.observer",
            "app.services.planning.revision",
        )
        for path in _scan(*AUTONOMY_MODULES):
            offenders = _imported_modules(path) & set(forbidden)
            assert offenders == set(), (path.name, offenders)

    def test_the_policy_layer_stays_pure(self):
        """D3 / D9：`autonomy_policy.py` 零仓储导入、零 IO（纯函数 + 纯数据）。"""
        path = _scan("app/engines/autonomy.py")[0]
        imported = _imported_modules(path)
        assert not [
            module for module in imported if module.startswith("app.repositories")
        ]
        assert not [
            module
            for module in imported
            if module.startswith(("sqlalchemy", "httpx", "requests", "socket"))
        ]
        assert "app.application" not in imported

    def test_planning_never_constructs_autonomy_contracts(self):
        for path in scan.planning_modules():
            names = _constructed_names(path)
            assert names & set(AUTONOMY_CONTRACT_TYPES) == set(), path.name
            assert "AutonomyVerdict" not in scan.code_text(path), path.name

    def test_planning_never_imports_the_autonomy_stack(self):
        forbidden = (
            "app.engines.autonomy",
            "app.application.autonomy_engine",
            "app.engines.decision",
            "app.services.autonomy.executor",
            "app.repositories.proactive_repository",
        )
        for path in scan.planning_modules():
            offenders = _imported_modules(path) & set(forbidden)
            assert offenders == set(), (path.name, offenders)

    def test_the_tool_layer_never_touches_plans_or_verdicts(self):
        for path in _scan(*TOOL_MODULES):
            assert path.exists(), path.name
            names = _constructed_names(path)
            assert names & set(PLAN_CONTRACT_TYPES) == set(), path.name
            assert names & set(AUTONOMY_CONTRACT_TYPES) == set(), path.name
            imported = _imported_modules(path)
            assert not [
                module for module in imported if module.startswith("app.services.planning")
            ], path.name

    def test_planning_never_creates_proactive_actions(self):
        """计划路径不产 `ProactiveAction`：拉取面与自治产品的写面互不相交。"""
        for path in scan.planning_modules():
            assert "proactive_repository" not in scan.code_text(path), path.name

    def test_autonomy_delegates_action_records_to_the_single_orchestrator(self):
        path = _scan("app/application/autonomy_engine.py")[0]
        text = scan.code_text(path)
        assert "run_action_planning" in text
        assert "ActionExecutor" not in text
        assert "ToolExecutor" not in text


class TestBoundaryRuntimeAssertions:
    """§8 Step 6.3：一次链路各层的输出类型恰为各自契约类型。"""

    def test_each_layer_returns_exactly_its_contract_type(self, db_session_factory):
        goal = support.seed_layered_goal(USER)
        plan = support.plan([support.spec(1)])

        verdict = autonomy_policy.evaluate(
            support.signal(), support.act_snapshot(), None, NOW
        )
        assert type(verdict) is AutonomyVerdict

        current = PlanScheduler.current_step(plan)
        assert type(current) is SubGoalSpec

        bridge = PlanExecutorBridge(session_resolver=lambda _user_id: None)
        intent = bridge.to_intent(goal, plan, current, support.bridge_ctx(NOW))
        assert type(intent) is ActionIntent

        outcome = PlanStepOutcome(
            step_index=current.index, status="succeeded", at=NOW, action_id="a1"
        )
        asserted = bridge.reconcile(outcome, current, max_attempts=2)
        assert type(asserted) is SubGoalSpec

        advance = PlanObserver().observe(goal, plan, {"now": NOW}, now=NOW)
        assert type(advance) is PlanAdvance
        assert type(PlanObserver().settle(goal, plan, advance)) is PlanSettlement

    def test_the_pipeline_returns_exactly_its_contract_type(self):
        result = decision_pipeline.run_pipeline(
            stack=None,
            snapshot=None,
            trigger_intention=support.CHECK_IN_INTENTION,
            now=NOW,
        )
        assert type(result) is decision_pipeline.DecisionResult
        assert type(result.winner) is decision_pipeline.Candidate

    def test_autonomy_run_writes_no_plan_rows(self, db_session_factory):
        goal = support.seed_layered_goal(USER)
        created = support.seed_plan(goal.id)
        before = goal_repository.get_plan(created.id)

        autonomy_policy.evaluate(
            support.signal(), support.barrier_snapshot(), None, NOW
        )
        decision_pipeline.run_pipeline(
            stack=None, snapshot=None, trigger_intention=None, now=NOW
        )

        assert goal_repository.get_plan(created.id) == before

    @staticmethod
    def _proactive_rows(user_id: str):
        return proactive_repository.list_since(NOW - timedelta(days=1))

    def test_planning_run_creates_no_proactive_action(self, db_session_factory):
        goal = support.seed_layered_goal(USER)
        plan = support.plan([support.spec(1)])
        PlanObserver().observe(goal, plan, {"now": NOW}, now=NOW)
        assert self._proactive_rows(USER) == []

    @staticmethod
    def _action_rows(user_id: str):
        return action_repository.list_records(user_id, limit=50)

    def test_a_plan_step_without_dispatch_creates_no_action_record(
        self, db_session_factory
    ):
        """未委托 Action 层时计划层零写：`action_records` 只由 Action 层入口写入。"""
        goal = support.seed_layered_goal(USER)
        plan = support.plan([support.spec(1)])
        before = self._action_rows(USER)
        PlanObserver().observe(goal, plan, {"now": NOW}, now=NOW)
        assert self._action_rows(USER) == before
