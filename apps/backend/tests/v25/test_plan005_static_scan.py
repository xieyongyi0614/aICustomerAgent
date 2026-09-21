"""PLAN-005 静态扫描断言：G-EXEC / G-WORLD / 纯函数纪律 / 零退避 / 零迁移。

Task Detail §9.2 的静态可判定部分（I1、I4、I12）与 §10.2 / §10.3 的红线。包级扫描
（角色资产放行面、`goal_repository` 调用白名单、零 session / 零 ORM 直写）见
`test_plan001_static_scan.py`——本任务的四个模块一并受其约束。
"""

import ast
import re
from pathlib import Path

from app.models.observability import DecisionKind
from app.repositories import goal_repository
from app.services.planning import executor_bridge, observer, scheduler
from app.services.planning import revision as revision_mod
from app.services.planning import goal_contract

from . import _plan_scan as scan

SCHEDULER_PATH = Path(scheduler.__file__)
BRIDGE_PATH = Path(executor_bridge.__file__)
OBSERVER_PATH = Path(observer.__file__)
REVISION_PATH = Path(revision_mod.__file__)

PLAN_005_MODULES = {
    "scheduler.py": SCHEDULER_PATH,
    "executor_bridge.py": BRIDGE_PATH,
    "observer.py": OBSERVER_PATH,
    "revision.py": REVISION_PATH,
}

PURE_MODULES = ("scheduler.py", "revision.py")

FORBIDDEN_EXECUTION_TOKENS = (
    "ToolExecutor",
    "Capability",
    "CapabilityExecutor",
    "ParamValidator",
    "world_repository",
)

FORBIDDEN_IO_PREFIXES = (
    "app.repositories",
    "app.application",
    "app.core.db",
    "sqlalchemy",
    "socket",
    "requests",
    "httpx",
)

MIGRATION_HEAD = "0052"

PLANNING_PACKAGE_MODULES = (
    "__init__.py",
    "context.py",
    "decompose.py",
    "engine.py",
    "executor_bridge.py",
    "goal_contract.py",
    "memory_policy.py",
    "observer.py",
    "revision.py",
    "revision_listener.py",
    "scheduler.py",
)


def _executable(path: Path) -> set[str]:
    return {
        node.func.id for node in scan.call_nodes(path) if hasattr(node.func, "id")
    }


def _attributes(path: Path, base: str) -> set[str]:
    return scan.called_attributes(path, base)


class TestModuleInventory:
    """范围标记的产物面：本任务新增四个模块。

    PLAN-009 落地后按同一纪律把 `memory_policy.py` 收进 `PLANNING_PACKAGE_MODULES`；
    PLAN-010 落地后同样把 `revision_listener.py` 收进该清单（本包模块清单已闭合，
    PLAN-011 / PLAN-012 不再新增模块）。
    """

    def test_planning_package_holds_exactly_the_landed_modules(self):
        names = sorted(
            path.name
            for path in scan.PLANNING_PACKAGE_DIR.rglob("*.py")
            if "__pycache__" not in path.parts
        )
        assert names == list(PLANNING_PACKAGE_MODULES)

    def test_plan_005_modules_are_discovered_by_the_package_scan(self):
        discovered = {path.name for path in scan.planning_modules()}
        assert set(PLAN_005_MODULES) <= discovered
        assert discovered <= set(PLANNING_PACKAGE_MODULES)

    def test_revision_listener_is_landed(self):
        """PLAN-010 契约演进（原「不得预埋」翻转为「已落地」）：Plan 侧反思接线。

        唯一 Planning 侧反思接线（§4.1.1 / architecture §7.6 ④）：本任务不新建第二个模块。
        """
        assert (scan.PLANNING_PACKAGE_DIR / "revision_listener.py").exists()
        assert not (scan.PLANNING_PACKAGE_DIR / "reflection.py").exists()
        assert not (scan.PLANNING_PACKAGE_DIR / "plan_reflection.py").exists()


class TestExecutionSingleEntryPoint:
    """I1 / G-EXEC：步骤执行只经 `action_engine.run_action_planning`，零直调工具层。"""

    def test_no_direct_tool_or_capability_execution(self):
        for name, path in PLAN_005_MODULES.items():
            assert scan.code_violations(path, FORBIDDEN_EXECUTION_TOKENS) == [], name

    def test_run_action_planning_is_the_only_executor_seam(self):
        imports = scan.import_from_names(BRIDGE_PATH)
        # v26 去门控（批次 7）：桥恒走 ActionManager，不再从 action_engine 导入执行入口。
        assert "run_action_planning" not in imports.get("app.application.action_engine", set())
        for name, path in PLAN_005_MODULES.items():
            executed = {
                node.func.attr
                for node in scan.call_nodes(path)
                if isinstance(node.func, ast.Attribute)
            }
            assert not (executed & {"run", "invoke"}), name
            if "execute" in executed:
                assert name == "executor_bridge.py", name
                source = path.read_text(encoding="utf-8")
                assert "action_manager.execute" in source
                assert "manager.execute" in source

    def test_no_parameter_revalidation_layer(self):
        """§5.2 校验分层：执行期 `ParamValidator.validate` 是唯一权威，本层零二次校验。"""
        assert scan.code_violations(BRIDGE_PATH, ("validate",)) == []

    def test_plan_max_steps_is_never_raised(self):
        """红线 3：多步由计划层编排，`action_plan_max_steps` 保持 1（本任务不写该设置）。"""
        for path in PLAN_005_MODULES.values():
            assert scan.code_violations(path, ("action_plan_max_steps",)) == []


class TestPureFunctionDiscipline:
    """D3 / §10.3：`PlanScheduler` 与 `PlanRevisionPolicy` 零 IO、零 LLM、零 settings 直调。"""

    def test_pure_modules_import_no_io_surface(self):
        for name in PURE_MODULES:
            path = PLAN_005_MODULES[name]
            offenders = [
                module
                for module in scan.imported_modules(path)
                for prefix in FORBIDDEN_IO_PREFIXES
                if module == prefix or module.startswith(prefix + ".")
            ]
            assert offenders == [], (name, offenders)

    def test_pure_modules_never_call_get_settings(self):
        for name in PURE_MODULES:
            assert "get_settings" not in _executable(PLAN_005_MODULES[name]), name

    def test_pure_modules_sort_only_by_structural_index(self):
        for name in PURE_MODULES:
            keys = scan.sort_key_sources(PLAN_005_MODULES[name])
            assert all(
                not any(
                    fragment in key
                    for fragment in scan.FORBIDDEN_SORT_KEY_FRAGMENTS
                )
                for key in keys
            ), name

    def test_observer_receives_facts_from_the_caller(self):
        """D9：`observe` 不自行采集事实（`collect_facts` 只在装配入口出现）。"""
        source = OBSERVER_PATH.read_text(encoding="utf-8")
        observe_body = source.split("def observe(", 1)[1].split("def settle(", 1)[0]
        assert "collect_facts" not in observe_body

    def test_zero_backoff_surface_in_every_module(self):
        """I4 / D8：Plan 层零退避、零等待（退避数学只有一份，在 Action 层）。"""
        for name, path in PLAN_005_MODULES.items():
            assert scan.code_violations(
                path, ("sleep", "backoff", "next_retry_at", "retry_delay", "time.sleep")
            ) == [], name


class TestRedLines:
    """§10.2 红线：零 world 写面 / 零角色状态写 / 零 ORM 行对象。"""

    def test_no_world_repository_import_anywhere_in_the_package(self):
        for path in scan.planning_modules():
            assert not [
                module
                for module in scan.imported_modules(path)
                if "world_repository" in module
            ], path.name

    def test_no_relationship_or_character_state_writes(self):
        forbidden = ("relationship_bridge", "character_state", "relationship_state")
        for name, path in PLAN_005_MODULES.items():
            assert scan.code_violations(path, forbidden) == [], name
            assert not [
                module
                for module in scan.imported_modules(path)
                if module.startswith("app.repositories.relationship")
            ], name

    def test_observer_memory_read_is_read_only(self):
        used = _attributes(OBSERVER_PATH, "memory_repository")
        assert used == {"list_top_salience"}

    def test_observer_goal_writes_stay_on_the_declared_face(self):
        used = _attributes(OBSERVER_PATH, "goal_repository")
        assert used <= set(goal_contract.PLANNING_GOAL_REPOSITORY_ALLOWED_CALLS)
        assert used == {"finish_goal", "get_goal", "list_active_plans"}
        assert scan.code_text(OBSERVER_PATH).count("goal_repository.finish_goal(") == 1

    def test_bridge_never_touches_goal_repository(self):
        """D6：`reconcile` 只写内存副本，落库由调用方完成（桥接层零仓储调用）。"""
        assert _attributes(BRIDGE_PATH, "goal_repository") == set()
        assert "goal_repository" not in scan.imported_modules(BRIDGE_PATH)

    def test_scheduler_and_revision_never_touch_repositories(self):
        for name in PURE_MODULES:
            path = PLAN_005_MODULES[name]
            assert not [
                module
                for module in scan.imported_modules(path)
                if module.startswith("app.repositories")
            ], name


class TestZeroMigration:
    """I14 / §10.3：迁移链头 0046、`ck_decision_records_kind` 五值、零新表新列。"""

    def test_migration_chain_head_is_still_0052(self):
        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        numbered = sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert f"{max(numbered):04d}" == MIGRATION_HEAD

    def test_decision_kind_value_set_is_unchanged(self):
        assert tuple(kind.value for kind in DecisionKind) == (
            "proactive_autonomy",
            "turn_goal",
            "turn_intention",
            "turn_behavior",
            "goal_lifecycle",
        )

    def test_plan_advance_reuses_the_goal_lifecycle_kind(self):
        assert observer.DecisionKind.GOAL_LIFECYCLE.value == "goal_lifecycle"
        assert "DecisionKind.GOAL_LIFECYCLE" in scan.code_text(OBSERVER_PATH)

    def test_no_orm_or_ddl_surface_in_the_new_modules(self):
        from app.core.db import Base

        plan_domain_tables = tuple(
            sorted(
                name
                for name in Base.metadata.tables
                if name in ("goal_plans", "plan_steps", "plan_tasks", "plan_advances")
            )
        )
        assert plan_domain_tables == ("goal_plans",), "计划域不得新建第二张表"
        for name, path in PLAN_005_MODULES.items():
            assert scan.import_from_names(path).get("app.core.db", set()) == set(), name
