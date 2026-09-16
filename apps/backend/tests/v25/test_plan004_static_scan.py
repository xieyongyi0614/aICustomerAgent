"""PLAN-004 静态扫描断言：复用面（零重复实现）/ 零新增映射与选择规则 / 纯函数纪律 / 零接线。

覆盖 Task Detail §9.2 的 I2、I3、I4、I6 与 §10.2 的两条红线（G-WORLD / G-EXEC）。
包级扫描（角色资产放行面、`goal_repository` 调用白名单、零 session / 零 ORM）见
`test_plan001_static_scan.py`——本任务的 `decompose.py` 一并受其约束。
"""

import ast
import inspect
import re
from pathlib import Path

from app.services.planning import decompose as decompose_mod
from app.services.planning import engine as plan_engine

from . import _plan_scan as scan

DECOMPOSE_PATH = Path(decompose_mod.__file__)
ENGINE_PATH = Path(plan_engine.__file__)

FORBIDDEN_MODULE_PREFIXES = (
    "app.repositories",
    "app.application",
    "app.core.db",
    "sqlalchemy",
    "socket",
    "requests",
    "httpx",
    "openai",
    "langchain",
    "langchain_core",
)

REGISTRY_WRITE_CALLS = (
    "register",
    "unregister",
    "record_outcome",
    "mark_tripped",
    "clear_tripped",
    "set_runtime_disabled",
    "clear_runtime_disabled",
)

MAPPING_CONSTANT_PATTERN = re.compile(r"dict\[str,\s*tuple\[str,\s*\.\.\.\]\]")

PUBLIC_SURFACE = (
    "DecompositionResult",
    "PlanValidator",
    "PlanStepSpec",
    "TaskDecomposer",
)

STAGE_FUNCTIONS = (
    "_parse_structure",
    "_bind_tools",
    "_complete_criteria",
    "_check_budget",
)

FROZEN_INTERFACE_FUNCTIONS = (
    "decompose",
    "validate_shape",
    "validate_binding",
    "validate_budget",
)


def test_decompose_module_is_discovered_by_the_package_scan():
    names = [path.name for path in scan.planning_modules()]
    assert "decompose.py" in names
    assert "app.services.planning.decompose" in scan.module_names()


def test_i2_structure_parsing_reuses_validate_sub_goals():
    """零重复实现：序号 / 前向依赖 / 深度封顶一律复用既有 `validate_sub_goals`。"""
    imported = scan.import_from_names(DECOMPOSE_PATH)
    assert "validate_sub_goals" in imported.get("app.models.goal", set())
    called = {
        node.func.id
        for node in scan.call_nodes(DECOMPOSE_PATH)
        if isinstance(node.func, ast.Name)
    }
    assert "validate_sub_goals" in called
    assert "SubGoalSpec" in imported.get("app.models.goal", set())


def test_i3_tiebreak_rule_is_delegated_to_the_existing_selector():
    """零自造排序：tiebreak 只经 `ToolSelector.select_with_reason`，且调用点唯一。"""
    select_calls = [
        node
        for node in scan.call_nodes(DECOMPOSE_PATH)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "select_with_reason"
    ]
    assert len(select_calls) == 1
    assert "ToolSelector" in scan.import_from_names(DECOMPOSE_PATH).get(
        "app.services.tool.surface", set()
    )
    assert scan.sort_key_sources(DECOMPOSE_PATH) == []


def test_i4_no_new_mapping_table_is_declared():
    """零新增映射表：能力 ↔ 工具反查一律读角色资产的 `ACTION_TOOL_MAP`。

    扫描口径用 `code_text`（丢弃注释与字符串）：契约文档本身必须能写出被禁的名字，
    故「名字出现在文档里」不算违规，「出现在可执行 token 里」才算。
    """
    assert MAPPING_CONSTANT_PATTERN.search(scan.code_text(DECOMPOSE_PATH)) is None
    assert "ACTION_TOOL_MAP" in scan.import_from_names(DECOMPOSE_PATH).get(
        "app.character.asuna.action", set()
    )
    assert scan.code_violations(DECOMPOSE_PATH, ("ACTION_CAPABILITY_MAP",)) == []


def test_i5_registry_is_only_read():
    """I5：绑定只读注册表——零注册 / 健康度 / 熔断 / 运行期禁用写入调用。"""
    used = {
        node.func.attr
        for node in scan.call_nodes(DECOMPOSE_PATH)
        if isinstance(node.func, ast.Attribute)
    }
    assert not (used & set(REGISTRY_WRITE_CALLS))
    assert {"resolve", "select_with_reason"} & used


def test_i6_no_io_surface_is_reachable_from_the_module():
    """I6：零 IO / 零 LLM——不导入仓储 / 应用层 / DB / 网络 / LLM，且不直调 `get_settings`。"""
    imported = scan.imported_modules(DECOMPOSE_PATH)
    assert not [
        module
        for module in imported
        for prefix in FORBIDDEN_MODULE_PREFIXES
        if module == prefix or module.startswith(prefix + ".")
    ]
    called = {
        node.func.id
        for node in scan.call_nodes(DECOMPOSE_PATH)
        if isinstance(node.func, ast.Name)
    }
    assert "get_settings" not in called
    assert scan.code_violations(DECOMPOSE_PATH, ("session.", "open(", "urlopen")) == []


def test_i6_validator_gates_are_declared_as_static_pure_functions():
    for gate in ("validate_shape", "validate_binding", "validate_budget"):
        attribute = inspect.getattr_static(decompose_mod.PlanValidator, gate)
        assert isinstance(attribute, staticmethod), gate
        assert not inspect.signature(getattr(decompose_mod.PlanValidator, gate)).parameters.get(
            "self"
        )


def test_g_world_and_g_exec_guards():
    """§10.2 红线：零 `world_repository` 导入；零 `ToolExecutor` / `Capability.execute` 调用。"""
    imported = scan.imported_modules(DECOMPOSE_PATH)
    assert not [module for module in imported if "world_repository" in module]
    assert scan.code_violations(
        DECOMPOSE_PATH, ("world_repository", "ToolExecutor", "Capability")
    ) == []
    executed = {
        node.func.attr
        for node in scan.call_nodes(DECOMPOSE_PATH)
        if isinstance(node.func, ast.Attribute)
    }
    assert "execute" not in executed
    assert "run" not in executed


def test_public_surface_is_the_frozen_four_plus_declarations():
    """§6.7：公开面仅 `decompose` + 三闸；分阶段函数与其余辅助一律模块私有。"""
    exported = set(decompose_mod.__all__)
    assert set(PUBLIC_SURFACE) <= exported
    assert not [name for name in STAGE_FUNCTIONS if name in exported]
    assert not [name for name in _prefixed_helpers() if name in exported]
    definitions = set(scan.function_definitions(DECOMPOSE_PATH))
    assert set(STAGE_FUNCTIONS) <= definitions
    assert set(FROZEN_INTERFACE_FUNCTIONS) <= definitions
    public = {
        name
        for name in definitions
        if not name.startswith("_") and name not in FROZEN_INTERFACE_FUNCTIONS
    }
    assert public == set(), f"模块内不得出现额外的公开函数：{sorted(public)}"


def _prefixed_helpers() -> set[str]:
    return {
        name
        for name in scan.function_definitions(DECOMPOSE_PATH)
        if name.startswith("_")
    }


def test_plan_004_does_not_wire_the_decomposer_into_the_engine():
    """零接线：PLAN-003 的引擎不调用拆解（接线属 PLAN-005 起的执行链）。"""
    assert "decompose" not in ENGINE_PATH.read_text(encoding="utf-8")
    assert "decompose" not in scan.imported_modules(ENGINE_PATH)
