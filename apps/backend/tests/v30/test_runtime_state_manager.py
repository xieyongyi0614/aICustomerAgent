"""RT-003 Runtime State Manager 测试：门面 / 版本 / 冻结 / 冲突 / 零写入。"""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from app.application.agent_runtime import state
from app.application.agent_runtime.contracts import (
    EVENT_STATE_VERSION_BUMPED,
    RuntimeEvent,
)
from app.models.agent_state import AgentStateSnapshot, CurrentFocus
from app.repositories import development_change_repository

STATE_PATH = Path(state.__file__)
FORBIDDEN_IMPORTS = (
    "app.chains",
    "app.prompts",
    "app.application.agent_runtime.llm_gateway",
    "app.channels.feishu",
)
FORBIDDEN_WRITE_TOKENS = ("session.add", ".commit(", "INSERT ", "UPDATE ", "DELETE ")

NOW = datetime(2026, 9, 21, 12, 0, 0)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_snapshot_delegates_to_assembler(monkeypatch):
    calls: list[tuple] = []
    sentinel = AgentStateSnapshot(snapshot_version=3)

    def _fake_assemble(user_id, character_id="asuna", now=None):
        calls.append((user_id, character_id, now))
        return sentinel

    monkeypatch.setattr(state.agent_state_assembler, "assemble", _fake_assemble)

    assert state.snapshot("u-snap", now=NOW) is sentinel
    assert calls == [("u-snap", "asuna", NOW)]


def test_version_dispatches_to_registered_source(monkeypatch):
    monkeypatch.setitem(
        state.DOMAIN_SOURCES,
        "relationship",
        lambda user_id, character_id, now: state.StateVersion(
            "relationship", 2, "ledger", NOW, NOW
        ),
    )

    result = state.version("relationship", "u-ver")

    assert result.basis == "ledger"
    assert result.version == 2


def test_version_snapshot_domain_uses_latest_archive_version(monkeypatch):
    row = SimpleNamespace(version=7, created_at=NOW)
    monkeypatch.setattr(
        state.agent_state_snapshot_repository, "latest", lambda user_id, character_id: row
    )

    result = state.version("character", "u-arc")

    assert result.basis == "snapshot"
    assert result.version == 7
    assert result.latest_at == NOW


def test_version_unavailable_domain_returns_none():
    result = state.version("unknown-domain", "u-none")

    assert result.basis == "unavailable"
    assert result.version is None


def test_activate_freezes_run_state(monkeypatch, override_settings):
    override_settings(runtime_state_versioning_enabled="true")

    def _fake_snapshot(user_id, character_id="asuna", now=None):
        return AgentStateSnapshot(snapshot_version=5)

    def _fake_version(domain, user_id, character_id="asuna", now=None):
        return state.StateVersion(domain, 1, "ledger", NOW, NOW)

    monkeypatch.setattr(state, "snapshot", _fake_snapshot)
    monkeypatch.setattr(state, "version", _fake_version)
    run = SimpleNamespace(data={}, started_at=NOW)

    first = state.activate(run, "u-freeze", now=NOW)
    second = state.activate(run, "u-freeze", now=NOW)

    assert first is second
    assert state.current(run) is first
    assert first.time_point == run.started_at


def test_activate_noop_when_flag_off(override_settings):
    override_settings(runtime_state_versioning_enabled="false")
    run = SimpleNamespace(data={}, started_at=NOW)

    assert state.activate(run, "u-off") is None
    assert "runtime_state" not in run.data
    assert state.current(run) is None


def test_reconcile_is_pure_and_reports_conflicts():
    agent_state = AgentStateSnapshot(
        mood="calm",
        energy=0.9,
        personality=[],
        current_focus=CurrentFocus(goal_id="g1"),
    )

    report = state.reconcile(
        agent_state,
        {"mood": "excited", "energy": 0.9, "personality": ["x"], "goal": "g2"},
    )

    resolutions = {conflict.domain: conflict.resolution for conflict in report.conflicts}
    assert resolutions["mood"] == "write_wins"
    assert resolutions["energy"] == "no_change"
    assert resolutions["personality"] == "snapshot_retained"
    assert resolutions["goal"] == "snapshot_retained"
    assert report.resolved["mood"] == "excited"


def test_observe_updates_cache_only():
    state.reset_observed_cache()
    event = RuntimeEvent(
        event_type=EVENT_STATE_VERSION_BUMPED,
        run_id="run-obs",
        session_id="s1",
        occurred_at=NOW,
    )

    state.observe("relationship", event)

    observed = state.observed_version("relationship", "run-obs")
    assert observed is not None
    assert observed.basis == "event"
    state.reset_observed_cache()
    assert state.observed_version("relationship", "run-obs") is None


def test_state_module_performs_no_writes():
    source = STATE_PATH.read_text(encoding="utf-8")
    assert not any(token in source for token in FORBIDDEN_WRITE_TOKENS)


def test_state_module_has_no_forbidden_imports():
    imported = _imported_modules(STATE_PATH)
    offenders = [
        name
        for name in imported
        if any(
            name == prefix or name.startswith(f"{prefix}.")
            for prefix in FORBIDDEN_IMPORTS
        )
    ]
    assert offenders == []


def test_development_change_repository_counts(db_session_factory):
    from app.core.db import DevelopmentChangeRow, DevelopmentStateRow

    with db_session_factory() as session:
        session.add(
            DevelopmentStateRow(
                id="ds-1",
                user_id="u-dev",
                character_id="asuna",
                kind="belief",
                key="k",
                value={},
                strength=1.0,
                source_insight_id="i-1",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            DevelopmentChangeRow(
                id="dc-1",
                development_state_id="ds-1",
                personality_state_id=None,
                before={},
                after={},
                insight_id="i-1",
                reason="compiled",
                created_at=NOW,
            )
        )
        session.commit()

    assert development_change_repository.count_changes("u-dev") == 1
    assert development_change_repository.latest_change("u-dev") == NOW


def test_development_version_reads_ledger(db_session_factory):
    from app.core.db import DevelopmentChangeRow, DevelopmentStateRow

    with db_session_factory() as session:
        session.add(
            DevelopmentStateRow(
                id="ds-2",
                user_id="u-dev-ver",
                character_id="asuna",
                kind="preference",
                key="k",
                value={},
                strength=1.0,
                source_insight_id="i-2",
                status="active",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            DevelopmentChangeRow(
                id="dc-2",
                development_state_id="ds-2",
                personality_state_id=None,
                before={},
                after={},
                insight_id="i-2",
                reason="compiled",
                created_at=NOW,
            )
        )
        session.commit()

    result = state.version("development", "u-dev-ver")

    assert result.basis == "ledger"
    assert result.version == 1
