"""RT-002 迁移一致性：Runtime 会话追踪列挂接与仓储过滤测试。

2026-09-29 迁移链折叠为单迁移 0001，本文件仅保留 ORM 最终态与仓储行为断言；
迁移链头一致性由 `tests/support/schema_pins.py` 统一钉测。
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.application import agent_runtime
from app.core.db import LoopRunRow, RuntimeTraceRow
from app.repositories import loop_run_repository

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_orm_has_session_id_and_correlation_id_columns():
    loop_columns = LoopRunRow.__table__.columns
    trace_columns = RuntimeTraceRow.__table__.columns

    assert "session_id" in loop_columns
    assert loop_columns["session_id"].nullable is True
    assert "correlation_id" in trace_columns
    assert trace_columns["correlation_id"].nullable is True


def test_indexes_declared():
    loop_indexes = {index.name for index in LoopRunRow.__table__.indexes}
    trace_indexes = {index.name for index in RuntimeTraceRow.__table__.indexes}

    assert "ix_loop_runs_session_id" in loop_indexes
    assert "ix_runtime_traces_correlation_id" in trace_indexes


def test_migration_chain_head_matches_pin():
    from tests.support.schema_pins import MIGRATION_HEAD

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == [MIGRATION_HEAD]


def test_list_recent_filters_by_session_id(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="true")
    run_a = agent_runtime.open_foreground_run("u-filter-a", session_id="S-A")
    agent_runtime.open_foreground_run("u-filter-b", session_id="S-B")

    rows = loop_run_repository.list_recent(session_id="S-A")

    assert [row.id for row in rows] == [run_a.run_id]


def test_legacy_rows_with_null_session_id_still_readable(
    db_session_factory, override_settings
):
    override_settings(runtime_session_tracking_enabled="false")
    legacy = agent_runtime.open_foreground_run("u-legacy")

    assert loop_run_repository.get(legacy.run_id).session_id is None
    assert legacy.run_id in [
        row.id for row in loop_run_repository.list_recent(user_id="u-legacy")
    ]
    assert loop_run_repository.list_recent(session_id="S-missing") == []
