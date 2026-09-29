"""TOOL-011 静态红线守门（§6.2、§9.5）：凭据零硬编码 / 无任意代码 / 无新依赖 / 无常驻 task。

AST 扫描实现（非正则），只解析源码、不 import 被测模块；fail-closed：新增依赖必须显式登记。
"""

import ast
import re
import sys
from pathlib import Path

import pytest

import yaml

NEW_MODULES = (
    Path("app/services/tool/ext_api.py"),
    Path("app/services/tool/dsl.py"),
    Path("app/services/tool/user_defined.py"),
)

MANIFESTS_DIR = Path("app/services/tool/manifests")

SECRET_NAMES = re.compile(r"(SECRET|TOKEN|PASSWORD|CREDENTIAL)", re.IGNORECASE)

FORBIDDEN_CALLS = frozenset({"eval", "exec", "compile", "open", "__import__"})

FORBIDDEN_ATTR_CALLS = frozenset({"import_module", "system", "popen", "spawn", "check_output"})

ALLOWED_IMPORT_ROOTS = frozenset({"__future__", "asyncio", "collections", "dataclasses", "json", "logging", "pathlib", "re", "socket", "typing", "urllib", "app", "app."})

EXPECTED_TASK_GLOBALS = frozenset(
    {
        "_observability_cleanup_task",
        "_job_worker_task",
        "_life_loop_task",
        "_agent_evolution_task",
    }
)
"""vXX_ 开关删除后：`_autonomy_task` / `_world_maintenance_task` /
`_action_maintenance_task` 三个兜底循环全局量已随 `main.py` 旧三循环一并移除
（life_loop 为唯一周期入口），故常驻 task 数由 8 降至 5。

2026-09-29 memory 域清理：v1 `memory_service.run_memory_reclaim_loop` 常驻循环移除
（`memories.expires_at` 已无任何写入者，该循环恒扫 0 行），常驻 task 数由 5 降至 4。"""

EXPECTED_CREATE_TASK_COUNT = 4


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _top_level_import_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _all_import_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _module_constants(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    constants: list[tuple[str, ast.AST]] = []
    for node in tree.body:
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        if value is None:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants.append((target.id, value))
    return constants


IDENTIFIER_LIKE = re.compile(r"^[a-z][a-z0-9_]*$")

HIGH_ENTROPY = re.compile(r"^[A-Za-z0-9+/=_-]{24,}$")


@pytest.mark.parametrize("path", NEW_MODULES)
def test_no_hardcoded_credentials(path):
    """AC：凭据零硬编码（静态扫描）。

    - 名称含 SECRET/TOKEN/PASSWORD/CREDENTIAL 的常量：值只能是标识符式枚举（如
      `credential_missing`）或空串，不得是疑似凭据的字面量。
    - 任何模块常量：不得出现高熵长串（真实 token/key 的形态）。
    """
    for name, value in _module_constants(_tree(path)):
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if SECRET_NAMES.search(name):
            assert value.value == "" or IDENTIFIER_LIKE.fullmatch(value.value), (
                f"{path}: 常量 {name} 疑似硬编码凭据"
            )
        assert not HIGH_ENTROPY.fullmatch(value.value), (
            f"{path}: 常量 {name} 疑似硬编码凭据（高熵字面量）"
        )


@pytest.mark.parametrize("path", NEW_MODULES)
def test_credentials_are_read_from_environment_only(path):
    text = path.read_text(encoding="utf-8")
    if path.name == "ext_api.py":
        assert "environ.get(" in text
        assert "os.environ" in text


@pytest.mark.parametrize("path", NEW_MODULES)
def test_no_arbitrary_code_execution(path):
    """安全红线：无任意代码执行原语。"""
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            assert func.id not in FORBIDDEN_CALLS, f"{path}:{node.lineno} 违规调用 {func.id}"
        else:
            assert getattr(func, "attr", "") not in FORBIDDEN_ATTR_CALLS, (
                f"{path}:{node.lineno} 违规调用 {getattr(func, 'attr', '')}"
            )


@pytest.mark.parametrize("path", NEW_MODULES)
def test_no_database_or_migration_access(path):
    """§3：本任务零新建表、零迁移（工具扩展面不触碰 DB / 迁移）。"""
    roots = _all_import_roots(_tree(path))
    assert "sqlalchemy" not in roots
    assert "alembic" not in roots
    for root in sorted(roots):
        assert root not in {"app.core.db", "app.repositories"}, root
    text = path.read_text(encoding="utf-8")
    assert "SessionLocal" not in text
    assert "alembic" not in text


@pytest.mark.parametrize("path", NEW_MODULES)
def test_no_new_third_party_dependency(path):
    """AC：不引入新第三方依赖（顶层 import 只允许标准库与 app.*）。"""
    roots = _top_level_import_roots(_tree(path))
    unexpected = {
        root
        for root in roots
        if root not in ALLOWED_IMPORT_ROOTS and root not in sys.stdlib_module_names
    }
    assert unexpected == set(), unexpected


def test_yaml_is_guarded_not_a_hard_dependency():
    """PyYAML 守卫式导入：只在函数内的 try 中 import，缺失即降级。"""
    tree = _tree(Path("app/services/tool/ext_api.py"))
    assert "yaml" not in _top_level_import_roots(tree)
    guarded = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Import) and any(
                alias.name == "yaml" for alias in child.names
            ):
                guarded = True
    assert guarded is True


def test_sample_manifests_reference_env_vars_only():
    files = sorted(MANIFESTS_DIR.glob("*.yaml"))
    assert files, "示例清单目录不得为空"
    for path in files:
        text = path.read_text(encoding="utf-8")
        payload = yaml.safe_load(text)
        auth = payload.get("http", {}).get("auth")
        if auth is None:
            continue
        assert set(auth) <= {"type", "env", "header"}
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", auth["env"])
        assert not re.search(
            r"(?:token|key|secret)\s*[:=]\s*[\"']?[A-Za-z0-9_\-/+=]{16,}", text, re.IGNORECASE
        ), path


def test_sample_manifests_hold_no_credentials():
    for path in sorted(MANIFESTS_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert "s3cr3t" not in text
        assert "Bearer " not in text


def test_env_example_ext_section_has_no_real_values():
    text = Path(".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(("TOOL_EXT_MANIFEST_PATH=", "TOOL_EXT_ALLOWED_HOSTS=")):
            assert line.endswith("="), line
    assert "TOOL_EXT_MANIFEST_PATH=" in text
    assert "TOOL_EXT_ALLOWED_HOSTS=" in text


def test_main_py_has_no_new_resident_task():
    """AC：main.py 不新增常驻 task（仅 lifespan 追加加载步骤；diff 断言）。"""
    tree = _tree(Path("app/main.py"))
    globals_ = {
        target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        for target in [node.target]
    } | {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id.endswith("_task")
    }
    assert globals_ == EXPECTED_TASK_GLOBALS

    create_task_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
    ]
    assert len(create_task_calls) == EXPECTED_CREATE_TASK_COUNT


def test_lifespan_loads_manifests():
    text = Path("app/main.py").read_text(encoding="utf-8")
    assert "get_manifest_loader().load(" in text


def test_capability_registry_registration_is_constant_folded():
    text = Path("app/services/action/capabilities/__init__.py").read_text(encoding="utf-8")
    assert "get_external_api_capability()" in text
    assert "if channel_tools_enabled():" in text


def test_normalizer_ext_branch_is_namespace_gated():
    text = Path("app/services/tool/normalizer.py").read_text(encoding="utf-8")
    assert 'if defn.namespace == EXT_API_NAMESPACE:' in text
    assert "UNTRUSTED_OBSERVATION_KEY" in text
