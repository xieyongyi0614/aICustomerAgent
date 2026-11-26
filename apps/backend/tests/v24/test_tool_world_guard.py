"""TOOL-007 §6.2 / E12 / E13：工具层世界写入静态护栏（AST 扫描 + 运行期兜底）。

红线（architecture §7.3）：**工具永不直接修改世界状态**——写世界只有一条路
`deferred_world_op` → `outbox_consumer._apply_world_op` → `world_engine`（唯一写面）。

本文件交付 `WorldWriteGuard`（TOOL-007 §4.3 的测试层实现）：

```text
scan_tool_modules(root) -> list[Violation]        AST 解析（不用正则，能区分 import 与调用）
assert_no_world_write(violations) -> None         非空即失败
```

**禁止导入**：`world_repository` / `character_state_repository` / `personality_state_repository` /
`relationship_*_repository` / `world_simulation_repository`。
**禁止调用**：`world_engine` 的非只读函数（只读白名单 `get_` / `list_` / `build_` / `find_`；
黑名单 `create_` / `move_` / `set_` / `apply_` / `discard_` / `consume_` / `expire_` 等写函数全在非白名单内）。
AST 覆盖**函数体内 import**（E12）与 `getattr(engine, "<写函数>")` 间接调用（E13 静态部分）；
变量名动态拼装的间接调用静态不可判，由 `install_world_write_backstop` 运行期兜底
（写前校验调用栈模块，E13 运行期部分）。
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"

TOOL_IMPLEMENTATION_ROOTS: tuple[Path, ...] = (APP_ROOT / "services" / "tool",)
"""扫描根：工具层模块。TOOL-010 的工具实现体落在此子树内（`services/tool/**`）；
若未来实现体落在别处，必须把该目录追加进来，否则护栏覆盖不到。"""

FORBIDDEN_IMPORT_NAMES: tuple[str, ...] = (
    "world_repository",
    "world_simulation_repository",
    "character_state_repository",
    "personality_state_repository",
)
"""禁止导入的仓储模块名（含关系域前缀规则，见 `_is_forbidden_import_name`）。"""

FORBIDDEN_RELATIONSHIP_PREFIX = "relationship_"

FORBIDDEN_CALL_PREFIXES: tuple[str, ...] = (
    "create_",
    "move_",
    "set_",
    "apply_",
    "discard_",
    "consume_",
    "expire_",
)
"""`world_engine` 写函数黑名单前缀（文档 §2.3 列举）。"""

ALLOWED_CALL_PREFIXES: tuple[str, ...] = ("get_", "list_", "build_", "find_")
"""`world_engine` 只读白名单前缀；白名单之外一律视为写面（含 `ensure_world` / `advance_time`）。"""

ENGINE_MODULE_SUFFIX = "world_engine"

KIND_FORBIDDEN_IMPORT = "forbidden_import"
KIND_FORBIDDEN_CALL = "forbidden_call"

ALLOWED_WORLD_WRITE_CALLERS: frozenset[str] = frozenset(
    {"app.application.outbox_consumer", "app.application.world_engine"}
)
"""唯一允许触发世界写入的模块（outbox 消费器；引擎自身内部调用）。"""

BACKSTOP_TEST_MODULE = __name__


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line} [{self.kind}] {self.detail}"


def _is_forbidden_import_name(name: str) -> bool:
    if name in FORBIDDEN_IMPORT_NAMES:
        return True
    return name.startswith(FORBIDDEN_RELATIONSHIP_PREFIX) and name.endswith("_repository")


def _forbidden_import_target(module: str | None, name: str) -> str | None:
    """`from <module> import <name>` / `import <module>` 命中禁止项时返回命中名。"""
    dotted = name if not module else f"{module}.{name}"
    for part in dotted.split("."):
        if _is_forbidden_import_name(part):
            return part
    return None


def _is_read_only_call(name: str) -> bool:
    return name.startswith(ALLOWED_CALL_PREFIXES)


def _call_detail(name: str) -> str:
    if name.startswith(FORBIDDEN_CALL_PREFIXES):
        return f"调用 world_engine 写函数: {name}（禁止前缀命中）"
    return f"调用 world_engine 非只读函数: {name}（只读白名单 get_/list_/build_/find_）"


def scan_source(source: str, filename: str = "<injected>") -> list[Violation]:
    """AST 扫描单份源码：检出禁止导入与 `world_engine` 非只读调用。

    `ast.walk` 覆盖函数体内的 import 与调用（E12）；不做正则匹配，避免把字符串常量误判。
    """
    tree = ast.parse(source, filename=filename)
    violations: list[Violation] = []
    engine_aliases: set[str] = set()
    engine_function_aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _forbidden_import_target(None, alias.name)
                if hit is not None:
                    violations.append(
                        Violation(filename, alias.lineno, KIND_FORBIDDEN_IMPORT, f"导入禁止仓储: {alias.name}")
                    )
                if alias.name.endswith(ENGINE_MODULE_SUFFIX):
                    engine_aliases.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                hit = _forbidden_import_target(module, alias.name)
                if hit is not None:
                    violations.append(
                        Violation(
                            filename,
                            alias.lineno,
                            KIND_FORBIDDEN_IMPORT,
                            f"导入禁止仓储: {module}.{alias.name}",
                        )
                    )
                if module.endswith(ENGINE_MODULE_SUFFIX):
                    bound = alias.asname or alias.name
                    if _is_read_only_call(alias.name):
                        engine_function_aliases[bound] = alias.name
                    else:
                        violations.append(
                            Violation(
                                filename,
                                alias.lineno,
                                KIND_FORBIDDEN_CALL,
                                f"直接导入 world_engine 写函数: {alias.name}",
                            )
                        )
                elif alias.name == ENGINE_MODULE_SUFFIX:
                    engine_aliases.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in engine_aliases
        ):
            if not _is_read_only_call(func.attr):
                violations.append(
                    Violation(filename, node.lineno, KIND_FORBIDDEN_CALL, _call_detail(func.attr))
                )
        elif isinstance(func, ast.Name) and func.id in engine_function_aliases:
            original = engine_function_aliases[func.id]
            if not _is_read_only_call(original):
                violations.append(
                    Violation(filename, node.lineno, KIND_FORBIDDEN_CALL, _call_detail(original))
                )
        elif (
            isinstance(func, ast.Name)
            and func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in engine_aliases
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and not _is_read_only_call(node.args[1].value)
        ):
            violations.append(
                Violation(
                    filename,
                    node.lineno,
                    KIND_FORBIDDEN_CALL,
                    f"getattr 间接调用 world_engine 写函数: {node.args[1].value}",
                )
            )
    return violations


def scan_paths(paths: list[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(paths):
        source = path.read_text(encoding="utf-8")
        violations.extend(scan_source(source, _display_path(path)))
    return violations


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(BACKEND_ROOT))
    except ValueError:
        return str(path)


def scan_tool_modules(root: str | Path | None = None) -> list[Violation]:
    """扫描工具层全部模块（§4.3）：返回违规清单，空列表即通过。"""
    roots = TOOL_IMPLEMENTATION_ROOTS if root is None else (Path(root),)
    targets: list[Path] = []
    for item in roots:
        targets.extend(
            path for path in item.rglob("*.py") if "__pycache__" not in path.parts
        )
    return scan_paths(targets)


def assert_no_world_write(violations: list[Violation]) -> None:
    """护栏断言：非空即失败（附完整违规清单）。"""
    assert not violations, "工具层出现世界直写违规：\n" + "\n".join(str(item) for item in violations)


# --- 运行期兜底（E13 动态间接调用）-------------------------------------------


def _caller_module_name() -> str:
    """写操作调用栈上第一个非本文件的模块名（即"谁在写世界"）。"""
    for frame_info in inspect.stack():
        module_name = frame_info.frame.f_globals.get("__name__", "")
        if module_name and module_name != BACKSTOP_TEST_MODULE:
            return str(module_name)
    return ""


def install_world_write_backstop(monkeypatch, engine=None) -> dict:
    """给 `world_engine` 全部写函数加"写前校验调用栈模块"断言（E13 运行期兜底）。

    静态扫描无法覆盖变量拼装的 `getattr` 动态调用；本兜底在真正落库前校验调用方模块，
    只放行消费器与引擎自身（`ALLOWED_WORLD_WRITE_CALLERS`）。返回调用记录，便于断言。
    """
    from app.application import world_engine as engine_module

    target = engine_module if engine is None else engine
    calls: list[tuple[str, str]] = []
    write_names = [
        name
        for name in dir(target)
        if name.startswith(FORBIDDEN_CALL_PREFIXES) and callable(getattr(target, name))
    ]
    for name in write_names:
        original = getattr(target, name)

        def wrapper(*args, _name: str = name, _original=original, **kwargs):
            caller = _caller_module_name()
            calls.append((_name, caller))
            if caller not in ALLOWED_WORLD_WRITE_CALLERS:
                raise RuntimeError(
                    f"世界直写被运行期兜底拦截: {_name} 由 {caller} 调用；"
                    "唯一写路径 = deferred_world_op → outbox → world_engine"
                )
            return _original(*args, **kwargs)

        monkeypatch.setattr(target, name, wrapper)
    return {"calls": calls, "guarded": tuple(write_names)}


# --- 护栏自检：真实工具层零违规 ----------------------------------------------


def test_tool_layer_has_no_forbidden_world_access():
    """§6.2：`app/services/tool/**` 零禁止导入、零禁止调用（真实树断言）。"""
    assert_no_world_write(scan_tool_modules())


def test_scan_is_not_vacuous_over_tool_tree():
    """护栏非空跑：扫描面确实覆盖到工具层模块（防止扫了个空目录还全绿）。"""
    targets = [
        path
        for root in TOOL_IMPLEMENTATION_ROOTS
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert len(targets) >= 8
    assert any(path.name == "world_context.py" for path in targets)


# --- E12：函数内动态 import 世界仓储 -----------------------------------------


def test_scan_detects_function_local_repository_import_e12():
    source = (
        "def load(user_id):\n"
        "    from app.repositories import world_repository\n"
        "    return world_repository.get_world(user_id)\n"
    )
    violations = scan_source(source, "injected_tool.py")
    assert [item.kind for item in violations] == [KIND_FORBIDDEN_IMPORT]
    assert violations[0].line == 2
    assert "world_repository" in violations[0].detail


@pytest.mark.parametrize(
    "statement",
    [
        "from app.repositories import world_repository",
        "from app.repositories import world_simulation_repository",
        "from app.repositories import character_state_repository",
        "from app.repositories import personality_state_repository",
        "from app.repositories import relationship_repository",
        "from app.repositories import relationship_event_repository",
        "from app.repositories import relationship_milestone_repository",
        "import app.repositories.world_repository",
        "from app.repositories.world_repository import save_world",
    ],
)
def test_scan_detects_all_forbidden_repositories(statement):
    violations = scan_source(f"{statement}\n", "injected_tool.py")
    assert [item.kind for item in violations] == [KIND_FORBIDDEN_IMPORT]


def test_scan_detects_forbidden_import_via_alias():
    violations = scan_source(
        "from app.repositories import world_repository as repo\n", "injected_tool.py"
    )
    assert len(violations) == 1 and violations[0].kind == KIND_FORBIDDEN_IMPORT


# --- E13：间接调用写函数（静态部分） -----------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        "world_engine.create_event()",
        "world_engine.move_object()",
        "world_engine.set_environment()",
        "world_engine.apply_object_action()",
        "world_engine.discard_object()",
        "world_engine.consume_object()",
        "world_engine.expire_due_objects()",
        "world_engine.ensure_world()",
        "world_engine.advance_time()",
    ],
)
def test_scan_detects_world_engine_write_calls(call):
    source = f"from app.application import world_engine\n{call}\n"
    violations = scan_source(source, "injected_tool.py")
    assert [item.kind for item in violations] == [KIND_FORBIDDEN_CALL]


def test_scan_detects_getattr_indirect_write_call_e13():
    source = (
        "from app.application import world_engine\n"
        "def write(op, args):\n"
        "    return getattr(world_engine, 'create_event')(*args)\n"
    )
    violations = scan_source(source, "injected_tool.py")
    assert [item.kind for item in violations] == [KIND_FORBIDDEN_CALL]
    assert violations[0].line == 3
    assert "create_event" in violations[0].detail


def test_scan_detects_write_function_direct_import():
    source = "from app.application.world_engine import create_event\n"
    violations = scan_source(source, "injected_tool.py")
    assert [item.kind for item in violations] == [KIND_FORBIDDEN_CALL]


def test_scan_detects_aliased_module_write_call():
    source = (
        "from app.application import world_engine as engine\n"
        "engine.set_location('home')\n"
    )
    violations = scan_source(source, "injected_tool.py")
    assert [item.kind for item in violations] == [KIND_FORBIDDEN_CALL]


# --- 只读函数不被误报 --------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        "world_engine.get_world('u')",
        "world_engine.get_objects_by_location('u', 'home')",
        "world_engine.list_active_objects('u')",
        "world_engine.list_active_events('u')",
        "world_engine.build_context('u')",
        "world_engine.find_object_by_name('u', '苹果')",
    ],
)
def test_read_only_calls_are_not_flagged(call):
    source = f"from app.application import world_engine\n{call}\n"
    assert scan_source(source, "injected_tool.py") == []


def test_read_only_direct_import_is_not_flagged():
    source = (
        "from app.application.world_engine import get_world, list_active_events\n"
        "world = get_world('u')\n"
        "events = list_active_events('u')\n"
    )
    assert scan_source(source, "injected_tool.py") == []


def test_getattr_with_read_only_name_is_not_flagged():
    source = (
        "from app.application import world_engine\n"
        "def read(user_id):\n"
        "    return getattr(world_engine, 'get_world')(user_id)\n"
    )
    assert scan_source(source, "injected_tool.py") == []


def test_other_modules_writes_are_not_flagged():
    """护栏只针对 `world_engine` 接收者：别的模块同名函数不在黑名单判定内。"""
    source = (
        "import logging\n"
        "from app.services.world import daily_plan\n"
        "daily_plan.get_current_block('u', None, 0)\n"
        "logging.getLogger(__name__).setLevel(1)\n"
    )
    assert scan_source(source, "injected_tool.py") == []


def test_strings_mentioning_write_calls_are_not_flagged():
    """AST 而非正则：字符串/注释里的写函数名不得误报。"""
    source = (
        "from app.application import world_engine\n"
        "# world_engine.create_event(...) 是唯一写面，工具层不得调用\n"
        "NOTE = 'world_engine.move_object'\n"
    )
    assert scan_source(source, "injected_tool.py") == []


# --- 人为注入违规代码：护栏捕获（目录级端到端） -------------------------------


def test_injected_violating_module_in_tree_is_caught(tmp_path):
    package = tmp_path / "services" / "tool"
    package.mkdir(parents=True)
    (package / "innocent.py").write_text(
        "from app.application import world_engine\n"
        "def read(user_id):\n"
        "    return world_engine.get_world(user_id)\n",
        encoding="utf-8",
    )
    assert scan_tool_modules(package) == []

    (package / "violating.py").write_text(
        "from app.repositories import world_repository\n"
        "from app.application import world_engine\n"
        "def write(user_id):\n"
        "    world_engine.move_object(user_id, 'obj-1', 'home')\n"
        "    return world_repository\n",
        encoding="utf-8",
    )
    violations = scan_tool_modules(package)
    assert {item.kind for item in violations} == {KIND_FORBIDDEN_IMPORT, KIND_FORBIDDEN_CALL}
    assert {Path(item.file).name for item in violations} == {"violating.py"}
    with pytest.raises(AssertionError):
        assert_no_world_write(violations)


def test_assert_no_world_write_reports_violations():
    violation = Violation("tool.py", 3, KIND_FORBIDDEN_CALL, "调用 world_engine 写函数: create_event")
    with pytest.raises(AssertionError) as excinfo:
        assert_no_world_write([violation])
    assert "tool.py:3" in str(excinfo.value)


# --- E13 运行期兜底：动态间接调用（静态不可判） -------------------------------


def _import_temp_tool_module(tmp_path, monkeypatch, body: str):
    """把"工具实现体"写进临时模块并导入，使调用栈确实来自工具层模块。"""
    import importlib
    import sys

    module_name = "tool_impl_violation"
    (tmp_path / f"{module_name}.py").write_text(body, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_backstop_blocks_tool_module_dynamic_write_e13(tmp_path, monkeypatch):
    """变量拼装的 `getattr` 静态扫不出 → 运行期兜底按调用栈模块拦截。"""
    backstop = install_world_write_backstop(monkeypatch)
    assert "create_event" in backstop["guarded"]
    tool_module = _import_temp_tool_module(
        tmp_path,
        monkeypatch,
        "from app.application import world_engine\n"
        "def write(op_name='create_event'):\n"
        "    return getattr(world_engine, op_name)('u-1')\n",
    )
    with pytest.raises(RuntimeError) as excinfo:
        tool_module.write()
    assert "运行期兜底拦截" in str(excinfo.value)
    assert backstop["calls"] == [("create_event", "tool_impl_violation")]


def test_backstop_allows_outbox_consumer_write_path(db_session_factory, monkeypatch):
    """唯一写路径不被兜底误伤：消费器调用通过，且落库成功。"""
    from datetime import datetime, timedelta

    from app.application import outbox_consumer, world_engine

    backstop = install_world_write_backstop(monkeypatch)
    assert backstop["guarded"]
    now = datetime(2026, 9, 14, 12, 0, 0)
    op = {
        "op": "create_event",
        "args": [
            "u-backstop",
            "reminder",
            "兜底放行",
            "high",
            (now + timedelta(hours=1)).isoformat(),
            "autonomy",
        ],
    }
    outbox_consumer._apply_world_op("act-backstop", op)

    world = world_engine.ensure_world("u-backstop")
    titles = [event.title for event in world_engine.list_active_events("u-backstop")]
    assert "兜底放行" in titles
    assert world is not None
    assert ("create_event", "app.application.outbox_consumer") in backstop["calls"]
    assert {caller for _, caller in backstop["calls"]} <= set(ALLOWED_WORLD_WRITE_CALLERS)
