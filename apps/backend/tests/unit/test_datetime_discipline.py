"""时间口径防回归护栏（时间口径统一收官批 §5.7；基线见 §6.4）。

三条断言：
1. 全库模型时间列一律 `UtcDateTime`（Postgres → `timestamptz`、SQLite 补 UTC）；
2. 模型与新迁移不出现裸 `DateTime(timezone=True)`；
3. `app/` 内无裸 `datetime.now()` / `utcnow()` 取时点（唯一取时口 `timeutil.now()`）。
"""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import DateTime

from app.core.db import Base
from app.core.db.base import UtcDateTime

pytestmark = pytest.mark.unit

BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"
DB_MODELS_ROOT = APP_ROOT / "core" / "db"
MIGRATIONS_ROOT = BACKEND_ROOT / "migrations" / "versions"

NAIVE_NOW_ALLOWLIST = {
    "app/core/timeutil.py",
    "app/core/clock.py",
    "app/core/ids.py",
    "app/services/world/time_provider.py",
}


def _naive_now_lines(path: Path) -> list[int]:
    """裸 `datetime.now()` / `utcnow()` 调用，以及把 `datetime.now` 当值传递（`default_factory`）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in {"now", "utcnow"}:
            continue
        receiver = node.value
        while isinstance(receiver, ast.Attribute):
            receiver = receiver.value
        if not (isinstance(receiver, ast.Name) and receiver.id in {"datetime", "dt"}):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call) and parent.func is node:
            if not parent.args and not parent.keywords:
                lines.append(node.lineno)
            continue
        lines.append(node.lineno)
    return lines


def test_all_model_datetime_columns_use_utc_datetime():
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime) and not isinstance(column.type, UtcDateTime)
    ]
    assert offenders == []


def test_model_sources_declare_no_raw_tz_datetime():
    offenders = [
        path.name
        for path in sorted(DB_MODELS_ROOT.glob("*.py"))
        if path.name != "base.py"
        and "DateTime(timezone=True)" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_new_migrations_declare_no_raw_tz_datetime():
    offenders = [
        path.name
        for path in sorted(MIGRATIONS_ROOT.glob("0*.py"))
        if not path.name.startswith("0001")
        and "timezone=True" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_naive_datetime_now_in_app():
    offenders: dict[str, list[int]] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if relative in NAIVE_NOW_ALLOWLIST:
            continue
        lines = _naive_now_lines(path)
        if lines:
            offenders[relative] = lines
    assert offenders == {}


def test_postgres_engine_pins_utc_session_timezone(monkeypatch):
    engine_module = import_module("app.core.db.engine")

    captured: dict = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(engine_module, "create_engine", fake_create_engine)
    engine_module.create_engine_from_url("postgresql+psycopg://u:p@localhost:5432/db")
    options = captured["kwargs"]["connect_args"]["options"]
    assert "-c timezone=UTC" in options
