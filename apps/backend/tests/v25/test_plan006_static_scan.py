"""PLAN-006 Step 5 / Step 7.2：G-EXEC 静态断言、零自造工具规则、零特判、执行入口唯一。

覆盖 Task Detail §9.2 I5 / I11 / I12 与 §10.3（零新增工具逻辑 / 零特判 / 治理未被稀释）。

扫描口径与 `tests/v25/_plan_scan.py` 一致：**代码口径**（丢弃注释与字符串）用于「禁止词」，
**AST 口径**（导入面 / 调用面 / 字面量面）用于结构断言。契约文档里必须能写出被禁的名字，
否则禁令无法被声明——故注释与 docstring 中的提及一律不算违规。

包级扫描（`goal_repository` 调用白名单、零 ORM 直写、角色资产放行面）见
`test_plan001_static_scan.py`；PLAN-005 四模块的纯函数纪律见 `test_plan005_static_scan.py`。
本模块只补 PLAN-006 的工具治理面。

清单留痕：`PLANNING_PACKAGE_MODULES` 在 PLAN-009 落地后按同一纪律收编
`memory_policy.py`（计划终态记忆边界表模块），其余条目逐字未动。
"""

import ast
from pathlib import Path

from app.models.action import ACTION_STATUSES, GATE_REASONS
from app.models.tool import (
    TOOL_EFFECT_KINDS,
    TOOL_EXECUTION_STATUSES,
    TOOL_FAILURE_KINDS,
    TOOL_NAMESPACES,
)
from app.services.planning import engine as engine_mod
from app.services.planning import goal_contract

from . import _plan_scan as scan

PLANNING_MODULES = scan.planning_modules()

ENGINE_PATH = Path(engine_mod.__file__)

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

FORBIDDEN_EXECUTION_TOKENS: tuple[str, ...] = (
    "ToolExecutor",
    "CapabilityExecutor",
    "Capability",
    "ToolHealthTracker",
    "ToolPermissionGate",
    "ParamValidator",
)
"""G-EXEC（§10.3）：规划层零直调执行器 / 能力 / 健康度 / 权限闸 / 校验器。"""

FORBIDDEN_ORCHESTRATOR_TOKENS: tuple[str, ...] = (
    "evaluate_gates",
    "assemble_plan",
    "execute_plan",
    "integrate_result",
)
"""既有 Action 编排器的内部环节名：规划层不得复制其实现（只能经唯一入口调用）。"""

HEALTH_WRITE_MEMBERS: tuple[str, ...] = (
    "record_outcome",
    "mark_tripped",
    "clear_tripped",
)

REGISTRY_WRITE_MEMBERS: tuple[str, ...] = (
    "register",
    "unregister",
    "set_runtime_disabled",
    "clear_runtime_disabled",
)

TOOL_ORDERING_CONSTANT_NAMES: tuple[str, ...] = (
    "TOOL_ORDER",
    "TOOL_PRIORITY",
    "TOOL_RANK",
    "TOOL_FILTER",
    "TOOL_WEIGHT",
    "TOOL_SCORE",
)

FORBIDDEN_SORT_KEY_FRAGMENTS: tuple[str, ...] = (
    "tool_id",
    "priority",
    "candidate",
    "surface",
    "tier",
    "score",
)
"""PLAN-006 追加的工具维排序关键词（PLAN-001 的红线集见 `_plan_scan`，此处为工具面补充）。"""

NAMESPACE_LITERALS: tuple[str, ...] = ("user", "ext.api")

ACTION_LAYER_IMPORT_PREFIXES: tuple[str, ...] = (
    "app.services.action",
    "app.application.action_engine",
)

EXPECTED_ACTION_LAYER_IMPORT: dict[str, set[str]] = {
    "executor_bridge.py": {"run_action_planning", "manager"},
}


def _call_attribute_names(path: Path) -> set[str]:
    return {
        node.func.attr
        for node in scan.call_nodes(path)
        if isinstance(node.func, ast.Attribute)
    }


def _name_literals(path: Path) -> set[str]:
    module = scan.tree(path)
    names: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


class TestPackageInventory:
    """范围标记：本任务不加模块（契约补齐与断言加固）。"""

    def test_planning_package_holds_exactly_the_landed_modules(self):
        names = sorted(path.name for path in PLANNING_MODULES)
        assert names == list(PLANNING_PACKAGE_MODULES)

    def test_no_task_local_module_is_planted(self):
        """PLAN-006 不新建模块：`planning/` 下不得出现本任务命名的实现文件。"""
        unexpected = [
            path.name
            for path in PLANNING_MODULES
            if "tool" in path.name or "gate" in path.name
        ]
        assert unexpected == []


class TestGExecStaticAssertions:
    """I5 / G-EXEC：`app/services/planning/` 零直调 `ToolExecutor` / `Capability.execute`。"""

    def test_no_execution_surface_token_in_the_package(self):
        for path in PLANNING_MODULES:
            assert scan.code_violations(path, FORBIDDEN_EXECUTION_TOKENS) == [], path.name

    def test_no_tool_or_capability_module_is_imported(self):
        forbidden_modules = (
            "app.services.tool.executor",
            "app.services.tool.health",
            "app.services.tool.validator",
            "app.services.tool.permission",
            "app.services.tool.normalizer",
            "app.services.action.executor",
            "app.services.action.planner",
            "app.services.action.registry",
        )
        for path in PLANNING_MODULES:
            imported = scan.imported_modules(path)
            assert imported & set(forbidden_modules) == set(), path.name

    def test_no_run_execute_or_invoke_call_in_the_package(self):
        for path in PLANNING_MODULES:
            called = _call_attribute_names(path)
            assert not (called & {"run", "invoke"}), path.name
            if "execute" in called:
                assert path.name == "executor_bridge.py", path.name

    def test_no_action_orchestrator_internals_are_reimplemented(self):
        for path in PLANNING_MODULES:
            assert scan.code_violations(path, FORBIDDEN_ORCHESTRATOR_TOKENS) == [], path.name

    def test_no_health_or_registry_writes(self):
        """只读消费：零健康度写入、零注册表写入（注册表快照必须不变）。"""
        for path in PLANNING_MODULES:
            calls = _call_attribute_names(path)
            assert calls & set(HEALTH_WRITE_MEMBERS) == set(), path.name
            assert calls & set(REGISTRY_WRITE_MEMBERS) == set(), path.name

    def test_the_registry_read_face_is_the_only_face_consumed(self):
        """注册表只读面：规划期只用 `get_tool_registry` / `ToolRegistry` / `TOOL_ID_PATTERN`。

        且 `engine.py` 对注册表实例的唯一调用是 `resolve`（闸门 5 的判定点，D1）。
        """
        allowed_names = {"get_tool_registry", "ToolRegistry", "TOOL_ID_PATTERN"}
        for path in PLANNING_MODULES:
            imported = scan.import_from_names(path).get("app.services.tool.registry", set())
            assert imported <= allowed_names, (path.name, imported)
        used = {
            node.func.attr
            for node in scan.call_nodes(ENGINE_PATH)
            if isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "registry"
        }
        assert used == {"resolve"}


class TestNoSelfMadeToolRules:
    """§10.3：`services/planning/` 零自造工具排序 / 过滤 / 映射规则。"""

    def test_the_tool_step_kind_matches_the_model_value_domain(self):
        """闸门 5/6 的判定类型必须落在模型层声明的 `StepKind` 值域内（漂移即失败）。"""
        from app.models.goal import STEP_KIND_VALUES, SubGoalSpec

        assert engine_mod.STEP_KIND_TOOL in STEP_KIND_VALUES
        assert SubGoalSpec.model_fields["kind"].default == engine_mod.STEP_KIND_TOOL
        assert "app.services.planning.decompose" not in scan.imported_modules(ENGINE_PATH)

    def test_no_tool_ordering_constant_is_declared(self):
        for path in PLANNING_MODULES:
            assert scan.code_violations(path, TOOL_ORDERING_CONSTANT_NAMES) == [], path.name

    def test_sort_keys_never_reference_the_tool_dimension(self):
        for path in PLANNING_MODULES:
            keys = scan.sort_key_sources(path)
            offenders = [
                key
                for key in keys
                if any(fragment in key for fragment in FORBIDDEN_SORT_KEY_FRAGMENTS)
            ]
            assert offenders == [], (path.name, offenders)

    def test_the_surface_projection_policy_is_never_reimplemented(self):
        for path in PLANNING_MODULES:
            source = scan.code_text(path)
            assert "should_exclude" not in source, path.name
            assert "SURFACE_LIMIT_REASON" not in source, path.name
            assert "TOOL_ID_PATTERN.fullmatch" in source or path.name != "decompose.py"

    def test_tool_selection_delegates_to_the_existing_selector(self):
        from app.services.planning import decompose as decompose_mod

        assert decompose_mod.ToolSelector is not None
        decompose_path = Path(decompose_mod.__file__)
        assert "select_with_reason" in scan.code_text(decompose_path)
        assert "SELECTION_REASON_" not in scan.code_text(decompose_path)


class TestZeroNamespaceSpecialCase:
    """Step 7.2 / §10.3：Planning 对扩展工具零特判分支。"""

    def test_no_namespace_literal_in_the_package(self):
        for path in PLANNING_MODULES:
            literals = scan.string_literals(path)
            offenders = [
                literal
                for literal in literals
                if literal in NAMESPACE_LITERALS
                or literal.startswith(("ext.api.", "user."))
            ]
            assert offenders == [], (path.name, offenders)

    def test_no_namespace_comparison_in_the_package(self):
        for path in PLANNING_MODULES:
            assert "namespace" not in _name_literals(path), path.name

    def test_declared_namespaces_are_not_consumed_by_planning(self):
        assert TOOL_NAMESPACES == ("builtin", "channel", "world", "ext.api", "user")
        for path in PLANNING_MODULES:
            assert "TOOL_NAMESPACES" not in scan.code_text(path), path.name


class TestExecutionEntryPointIsUnique:
    """Step 5.3：`action_engine.run_action_planning` 是计划层唯一触达 Action 层的函数。"""

    def test_action_layer_imports_are_limited_to_the_single_entry(self):
        discovered: dict[str, set[str]] = {}
        for path in PLANNING_MODULES:
            imported = scan.import_from_names(path)
            names = {
                name
                for module, module_names in imported.items()
                for name in module_names
                if module.startswith(ACTION_LAYER_IMPORT_PREFIXES)
            }
            if names:
                discovered[path.name] = names
        assert discovered == EXPECTED_ACTION_LAYER_IMPORT

    def test_no_other_module_touches_the_action_engine(self):
        for path in PLANNING_MODULES:
            if path.name == "executor_bridge.py":
                continue
            imported = scan.imported_modules(path)
            assert "app.application.action_engine" not in imported, path.name


class TestToolLayerDoesNotDependOnPlanning:
    """I12：V2.4.0 工具侧零改动——工具层与行动编排器不得反向依赖计划层。"""

    TOOL_LAYER_FILES = (
        "app/services/tool/registry.py",
        "app/services/tool/surface.py",
        "app/services/tool/executor.py",
        "app/services/tool/permission.py",
        "app/services/tool/validator.py",
        "app/services/tool/health.py",
        "app/services/tool/confirmation.py",
        "app/services/tool/normalizer.py",
        "app/services/tool/builtin.py",
        "app/services/tool/dsl.py",
        "app/services/tool/ext_api.py",
        "app/services/tool/user_defined.py",
        "app/services/tool/memory_policy.py",
        "app/services/tool/world_intent.py",
    )

    def test_no_tool_layer_module_imports_planning(self):
        backend_root = Path(goal_contract.__file__).parents[3]
        for relative in self.TOOL_LAYER_FILES:
            path = backend_root / relative
            assert path.exists(), relative
            offenders = [
                module
                for module in scan.imported_modules(path)
                if module.startswith("app.services.planning")
            ]
            assert offenders == [], (relative, offenders)

    def test_action_engine_does_not_import_planning(self):
        backend_root = Path(goal_contract.__file__).parents[3]
        path = backend_root / "app" / "application" / "action_engine.py"
        offenders = [
            module
            for module in scan.imported_modules(path)
            if module.startswith("app.services.planning")
        ]
        assert offenders == []

    def test_tool_layer_keeps_its_frozen_value_sets(self):
        """I11：工具侧值集零新增——`ToolExecutor` / `ToolResult` 契约未被 PLAN-006 触碰。"""
        assert TOOL_EXECUTION_STATUSES == (
            "succeeded",
            "failed",
            "timeout",
            "unavailable",
            "denied",
            "invalid",
            "pending_confirmation",
        )
        assert TOOL_FAILURE_KINDS == (
            "transient",
            "permanent",
            "timeout",
            "unavailable",
            "denied",
            "invalid",
        )
        assert TOOL_EFFECT_KINDS == (
            "world",
            "memory",
            "relationship",
            "note",
            "external",
        )

    def test_action_value_sets_are_not_extended(self):
        """§4.3.2：`ActionStatus` 六值、`GATE_REASONS` 十值均未扩。"""
        assert ACTION_STATUSES == (
            "created",
            "planned",
            "executing",
            "succeeded",
            "failed",
            "cancelled",
        )
        assert GATE_REASONS == (
            "disabled",
            "ambiguous_params",
            "capability_unavailable",
            "duplicate",
            "quota_exceeded",
            "effect_already_satisfied",
            "target_not_found",
            "permission_denied",
            "invalid_params",
            "pending_confirmation",
        )
        assert len(GATE_REASONS) == 10
