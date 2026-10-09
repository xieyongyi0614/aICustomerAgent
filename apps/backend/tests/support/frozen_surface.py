"""冻结面摘要工具（T-24）：比对前先暴露实际摘要，治「摘要静默 stale」误判。

背景：多处钉测用「整文件 sha256」冻结文件（`ZERO_DIFF_HASHES` /
`FROZEN_SOURCES`）。实际踩过的坑——**常量会静默 stale**：2026-09-28 实测
`world_engine.py` 在「本次改动之前」就已经是红的（上一次改动忘了同步摘要），
判读者无法从「assert 失败」本身区分「是我改坏的」还是「旧账」。

本模块把比对拆成两步并**总是先打印实际摘要**：

    actual = file_digest("app/application/world_engine.py")
    assert_frozen("app/application/world_engine.py", expected=digest, actual=actual)

失败信息同时给出 expected 与 actual，并提示「重算命令」，使判读成本降到最低。
**本模块只做诊断呈现，不改变任何摘要常量，也不放宽断言。**

摘要算法与既有实现保持一致（`test_tool010_e2e.py::_file_digest` 同款）：
读字节 → 把 `\\r\\n` 归一为 `\\n` → sha256 hexdigest。
行尾归一抵消 `core.autocrlf=true` 检出带来的假失败。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

CRLF = b"\r\n"
LF = b"\n"

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def file_digest(relative_path: str) -> str:
    """返回相对 `apps/backend/` 的文件摘要（行尾归一 LF 后 sha256）。"""
    data = (_BACKEND_ROOT / relative_path).read_bytes().replace(CRLF, LF)
    return hashlib.sha256(data).hexdigest()


def digest_report(relative_path: str) -> str:
    """返回可直接粘进钉测常量的摘要行（供人工同步时取用）。"""
    return f'{relative_path}: "{file_digest(relative_path)}"'


def assert_frozen(relative_path: str, *, expected: str, actual: str | None = None) -> None:
    """断言冻结摘要一致；失败时**同时打印 actual 与 expected**（T-24）。

    `actual` 由调用方传入以避免重复读盘（调用方通常已算过）；缺省时现算。
    """
    if actual is None:
        actual = file_digest(relative_path)
    if actual == expected:
        return

    raise AssertionError(
        f"\n{'=' * 72}\n"
        f"[冻结面失配] {relative_path}\n"
        f"  expected (钉测常量) : {expected}\n"
        f"  actual   (磁盘现状) : {actual}\n"
        f"{'-' * 72}\n"
        f"判读指引：\n"
        f"  1) 若本次**确实**改动了该文件 → 属预期，同步常量即可：\n"
        f"       {digest_report(relative_path)}\n"
        f"  2) 若本次**未**改动该文件 → 该常量早已 stale（旧账），\n"
        f"     需查最近一次改此文件的 commit 当时是否漏同步；\n"
        f"     在确认磁盘内容正确后同样按上一行同步。\n"
        f"  ⚠️ 不得为「让测试变绿」而把 expected 改成 actual 而不理解差异。\n"
        f"{'=' * 72}"
    )
