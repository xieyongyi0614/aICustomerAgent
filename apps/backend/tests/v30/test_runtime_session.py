"""RT-002 Session 生命周期 / Run 挂接 / 开关门控测试。"""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.application import agent_runtime
from app.application.agent_runtime import session as session_module
from app.application.agent_runtime.controller import close_run
from app.application.agent_runtime.session import (
    build_session_context,
    close_session,
    open_session,
    resume_session,
)
from app.repositories import loop_run_repository
from app.services.channel_identity_service import build_session_id

SESSION_PATH = Path(session_module.__file__)
FORBIDDEN = ("app.chains", "app.prompts", "app.channels.feishu", "conversation_repository")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _boom(*_args, **_kwargs):
    raise AssertionError("session 只读面不得触发写路径")


def test_open_session_derives_session_id_from_channel_identity():
    context = open_session("feishu", "ou_x")
    assert context.session_id == build_session_id("feishu", "ou_x")


def test_open_session_is_pure_and_returns_frozen_context():
    first = open_session("feishu", "ou_x")
    second = open_session("feishu", "ou_x")
    assert first.session_id == second.session_id
    assert first.channel == "feishu"
    with pytest.raises(FrozenInstanceError):
        setattr(first, "channel", "web")


def test_build_session_context_validates_session_id():
    with pytest.raises(ValueError):
        build_session_context("")


def test_resume_session_returns_none_without_runs(db_session_factory):
    assert resume_session("session-with-no-runs") is None


def test_resume_session_rebuilds_from_ledger(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="true")
    run = agent_runtime.open_foreground_run("u-resume", session_id="S-resume")

    context = resume_session("S-resume")

    assert context is not None
    assert context.session_id == "S-resume"
    assert context.trigger_type == "channel_message"
    assert context.run_id == run.run_id


def test_close_session_aggregates_runs(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="true")
    done_run = agent_runtime.open_foreground_run("u-agg", session_id="S-agg")
    degraded_run = agent_runtime.open_foreground_run("u-agg", session_id="S-agg")
    close_run(done_run, "done")
    close_run(degraded_run, "degraded")

    summary = close_session(build_session_context("S-agg"))

    assert summary.run_count == 2
    assert summary.status_counts == {"done": 1, "degraded": 1}


def test_close_session_does_not_write_any_table(db_session_factory, monkeypatch):
    for name in ("create_run", "mark_step", "finish_run"):
        monkeypatch.setattr(loop_run_repository, name, _boom)

    summary = close_session(build_session_context("S-readonly"))

    assert summary.run_count == 0


def test_flag_off_means_no_session_column_write(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="false")

    run = agent_runtime.open_foreground_run("u-sess-off", session_id="S-off")

    assert loop_run_repository.get(run.run_id).session_id is None


def test_flag_on_writes_session_id(db_session_factory, override_settings):
    override_settings(runtime_session_tracking_enabled="true")

    run = agent_runtime.open_foreground_run("u-sess-on", session_id="S-on")

    assert loop_run_repository.get(run.run_id).session_id == "S-on"


def test_session_module_has_no_forbidden_imports():
    imported = _imported_modules(SESSION_PATH)
    offenders = [
        name
        for name in imported
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in FORBIDDEN)
    ]
    assert offenders == []
