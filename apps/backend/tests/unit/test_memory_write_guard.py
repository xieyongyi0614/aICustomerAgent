"""记忆写入口守卫（2026-10-16）：`create_memory*` 直调点必须经类型归一。

背景：`memory_repository.create_memory` / `create_memory_and_supersede` 按
`VALID_MEMORY_TYPES`（7 规范值）校验 `memory_type`，但**不做归一**——归一责任在调用方
（2026-10-15 写入口收口：动作能力与计划终态两处直调点各接 `normalize_type`；其余路径经
`ingest.create_candidate` / `evaluator._final_type` 归一）。本守卫把「全仓直调点清单」冻结：
新增直调点即红，迫使作者显式决定归一点，或在此登记说明。

判据：
1) 直调点集合 == 冻结清单（文件 + 所在函数）；
2) 每个直调点所在函数体内必须出现 `normalize_type(` 调用。

仓储自身（定义处）不计入；测试侧调用不在守卫范围（只扫 `app/`）。
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"

WRITE_ENTRY_NAMES = ("create_memory", "create_memory_and_supersede")

REPOSITORY_MODULE = "app/repositories/memory_repository.py"

EXPECTED_CALL_SITES: frozenset[tuple[str, str]] = frozenset(
    {
        ("app/services/action/capabilities/memory.py", "execute"),
        ("app/services/planning/memory_policy.py", "_deliver"),
    }
)

NORMALIZE_CALL = "normalize_type("


def _innermost_function(tree: ast.AST, node: ast.AST):
    innermost = None
    for candidate in ast.walk(tree):
        if not isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = candidate.end_lineno or candidate.lineno
        if candidate.lineno <= node.lineno <= end:
            if innermost is None or candidate.lineno > innermost.lineno:
                innermost = candidate
    return innermost


def _function_source(source: str, function) -> str:
    end = function.end_lineno or function.lineno
    return "\n".join(source.splitlines()[function.lineno - 1 : end])


def _call_sites() -> dict[tuple[str, str], str]:
    """返回 {(相对路径, 所在函数名): 该函数源码}。"""
    sites: dict[tuple[str, str], str] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if relative == REPOSITORY_MODULE:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr not in WRITE_ENTRY_NAMES:
                continue
            function = _innermost_function(tree, node)
            scope = "<module>" if function is None else function.name
            body = "" if function is None else _function_source(source, function)
            sites[(relative, scope)] = body
    return sites


def test_call_sites_are_the_frozen_inventory():
    sites = _call_sites()
    assert set(sites) == set(EXPECTED_CALL_SITES), (
        "记忆写入口直调点发生变化：新增直调点必须经 `normalize_type` 归一并在此登记；"
        f"实际={sorted(sites)}"
    )


def test_every_call_site_normalizes_type():
    for (relative, scope), body in _call_sites().items():
        assert NORMALIZE_CALL in body, (
            f"{relative}::{scope} 直调 `create_memory*`，但该函数体内未归一"
            f"（缺 `{NORMALIZE_CALL}`）"
        )
