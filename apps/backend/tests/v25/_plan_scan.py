"""PLAN-001 静态扫描工具（测试专用，不属运行期代码）。

用途：把 Task Detail §8 Step 3 / Step 5.3 的三条静态断言写成可执行、可回归的形式，
并让后续任务（PLAN-002 ~ PLAN-012）在同一套扫描器上继续受约束。

扫描口径（两套，各司其职）：

- **代码口径**（`code_text` / `code_call_names`）：经 `tokenize` 丢弃 COMMENT 与 STRING，
  只保留可执行 token 与 AST 节点。文档字符串与注释中的「禁止词」不构成违规
  —— 契约声明本身必须能写出这些词，否则无法声明禁令。
  代价：把违规藏进字符串字面量即可绕过此口径，故另有 AST 口径兜底。
- **AST 口径**（`imported_modules` / `called_attributes` / `call_nodes` / `string_literals`）：
  看真实语法结构，不受注释与字符串影响，用于导入面、调用面与字面量面的断言。
"""

import ast
import tokenize
from io import StringIO
from pathlib import Path

import app.services.planning as planning_package

PLANNING_PACKAGE_DIR = Path(planning_package.__file__).parent

FORBIDDEN_CHARACTER_IMPORT_PREFIX = "app.character"

FORBIDDEN_CODE_NAMES = ("GoalRow", "GoalPlanRow", "GOAL_TIER")

FORBIDDEN_CODE_FRAGMENTS = (
    "session.execute",
    "session.add",
    "session.commit",
    "session.query",
    "session.flush",
    "session.merge",
)

FORBIDDEN_SQLALCHEMY_WRITE_CALLS = ("update", "insert", "delete")

FORBIDDEN_SQL_LITERAL_FRAGMENTS = (
    "character_goals",
    "goal_plans",
    "UPDATE ",
    "INSERT INTO",
    "DELETE FROM",
)

FORBIDDEN_SORT_KEY_FRAGMENTS = ("priority", "tier", "GOAL_TIER", "score")

REPO_ROOT = PLANNING_PACKAGE_DIR.parents[2]


def planning_modules() -> list[Path]:
    return sorted(
        path
        for path in PLANNING_PACKAGE_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def planning_module_paths() -> list[str]:
    """planning 包内全部模块的相对包路径（posix，含子包文件）。

    清单守卫统一语义：单文件为 `name.py`，子包文件为 `pkg/file.py`——
    包化不再与「计划包只含已落地模块」的精确清单断言冲突。
    """
    return sorted(
        path.relative_to(PLANNING_PACKAGE_DIR).as_posix()
        for path in PLANNING_PACKAGE_DIR.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def module_name(path: Path) -> str:
    parts = list(path.relative_to(REPO_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def module_names() -> list[str]:
    return [module_name(path) for path in planning_modules()]


def code_tokens(path: Path) -> list[tokenize.TokenInfo]:
    source = path.read_text(encoding="utf-8")
    return [
        token
        for token in tokenize.generate_tokens(StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    ]


def code_text(path: Path) -> str:
    """紧凑拼接的可执行文本（无分隔符，使 `session.execute` 这类点号片段可匹配）。"""
    return "".join(token.string for token in code_tokens(path))


def code_lines(path: Path) -> list[tuple[int, str]]:
    grouped: dict[int, list[str]] = {}
    for token in code_tokens(path):
        if token.type in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT):
            continue
        grouped.setdefault(token.start[0], []).append(token.string)
    return sorted((line, "".join(parts)) for line, parts in grouped.items())


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def import_from_names(path: Path) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.setdefault(node.module, set()).update(
                alias.name for alias in node.names
            )
    return names


def called_attributes(path: Path, base: str) -> set[str]:
    """`<base>.<attr>` 形态的全部属性访问名（含读取，不含仅字符串出现）。"""
    found: set[str] = set()
    for node in ast.walk(tree(path)):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == base
        ):
            found.add(node.attr)
    return found


def call_nodes(path: Path) -> list[ast.Call]:
    return [node for node in ast.walk(tree(path)) if isinstance(node, ast.Call)]


def function_definitions(path: Path) -> list[str]:
    return [
        node.name
        for node in ast.walk(tree(path))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def string_literals(path: Path) -> set[str]:
    """非文档字符串的字面量（文档字符串与代码注释同口径排除）。"""
    module = tree(path)
    docstrings = _docstring_node_ids(module)
    return {
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }


def _docstring_node_ids(module: ast.Module) -> set[int]:
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    ids: set[int] = set()
    for node in ast.walk(module):
        if not isinstance(node, holders):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def code_violations(path: Path, tokens: tuple[str, ...]) -> list[str]:
    text = code_text(path)
    return [token for token in tokens if token in text]


def literal_violations(path: Path, fragments: tuple[str, ...]) -> list[str]:
    literals = string_literals(path)
    return [
        fragment
        for fragment in fragments
        if any(fragment in literal for literal in literals)
    ]


def goal_repository_call_names(path: Path) -> set[str]:
    """模块内触达 `goal_repository` 的成员名（属性访问 + 具名导入，保守取并集）。"""
    names = called_attributes(path, "goal_repository")
    names |= import_from_names(path).get("app.repositories.goal_repository", set())
    return names



def simple_call_names(path: Path) -> set[str]:
    """裸函数调用名（`update(...)` / `execute(...)` 形态，不受限定前缀影响）。"""
    names: set[str] = set()
    for node in call_nodes(path):
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names


def sort_key_sources(path: Path) -> list[str]:
    """`sorted(..., key=...)` / `list.sort(key=...)` 的 key 表达式源码。"""
    source = path.read_text(encoding="utf-8")
    keys: list[str] = []
    for node in call_nodes(path):
        is_sort = (
            isinstance(node.func, ast.Name)
            and node.func.id == "sorted"
        ) or (isinstance(node.func, ast.Attribute) and node.func.attr == "sort")
        if not is_sort:
            continue
        for keyword in node.keywords:
            if keyword.arg == "key":
                keys.append(ast.get_source_segment(source, keyword.value) or "")
    return keys
