"""state_service._capture_snapshot_if_needed 关键帧 trigger 防回归单测。

回归背景：conflict_transition 曾被声明为 tuple 并按 (old, new) 解包，而实际传入的是
relationship_conflict 的具名迁移字符串（空串 = 本轮无迁移），空串既非 None 也不可解包，
导致每轮无冲突回合都抛 ValueError。
"""

from datetime import datetime

import pytest

from app.models.relationship import RelationshipState
from app.repositories import relationship_snapshot_repository as snapshot_repo
from app.services.state_service import _capture_snapshot_if_needed

NOW = datetime(2026, 3, 1, 12, 0, 0)


@pytest.fixture
def snapshot_session(db_session_factory, monkeypatch):
    """把快照仓储接到内存 SQLite（该仓储不在 conftest 的 autouse 覆盖列表内）。"""
    monkeypatch.setattr(snapshot_repo, "SessionLocal", db_session_factory)
    return db_session_factory


def _state(stage: str, version: int) -> RelationshipState:
    return RelationshipState(stage=stage, version=version)


def _capture(snapshot_session, user_id, state_before, state_after, stage_before, conflict_transition):
    _capture_snapshot_if_needed(
        user_id,
        state_before=state_before,
        state_after=state_after,
        stage_before=stage_before,
        conflict_transition=conflict_transition,
        new_milestones=[],
        now=NOW,
    )
    return snapshot_repo.list_snapshots(user_id)


def test_no_conflict_transition_writes_no_snapshot(snapshot_session):
    snapshots = _capture(
        snapshot_session,
        "u_no_conflict",
        _state("friend", 1),
        _state("friend", 2),
        "friend",
        "",
    )
    assert snapshots == []


def test_conflict_transition_writes_snapshot_with_named_trigger(snapshot_session):
    snapshots = _capture(
        snapshot_session,
        "u_conflict",
        _state("friend", 1),
        _state("friend", 2),
        "friend",
        "reconciled",
    )
    assert len(snapshots) == 1
    assert snapshots[0].trigger == "conflict:reconciled"
    assert snapshots[0].version == 2


def test_stage_transition_takes_priority_over_conflict(snapshot_session):
    snapshots = _capture(
        snapshot_session,
        "u_stage",
        _state("friend", 1),
        _state("close_friend", 2),
        "friend",
        "conflict_started",
    )
    assert len(snapshots) == 1
    assert snapshots[0].trigger == "stage_transition:friend→close_friend"


def test_all_named_conflict_transitions_are_safe(snapshot_session):
    """每种具名迁移字符串都必须能拼出 trigger，不得触发解包崩溃。"""
    expected = (
        "conflict_started",
        "strain_started",
        "strain_relieved",
        "cold_started",
        "recovery_started",
        "reconciled",
        "recovery_fallback",
        "conflict_reopened",
    )
    for index, transition in enumerate(expected):
        user_id = f"u_transition_{index}"
        _capture(
            snapshot_session,
            user_id,
            _state("friend", 1),
            _state("friend", 2),
            "friend",
            transition,
        )
        snapshots = snapshot_repo.list_snapshots(user_id)
        assert [s.trigger for s in snapshots] == [f"conflict:{transition}"]
