"""V8.5 relationship_snapshots 仓储集成测试（persistence.md §4~§6）。"""

import pytest

from app.core.db import Base
from app.models.relationship import RelationshipState
from app.repositories import relationship_snapshot_repository as repo


@pytest.fixture
def session_factory(db_session_factory, monkeypatch):
    monkeypatch.setattr(repo, "SessionLocal", db_session_factory)
    return db_session_factory


def _state(version: int, trust: float) -> RelationshipState:
    return RelationshipState(trust=trust, version=version)


def test_create_and_list_snapshots_descending(session_factory):
    for version in range(1, 4):
        repo.create_snapshot("u1", version, _state(version, 0.3 + version * 0.1))
    snapshots = repo.list_snapshots("u1")
    assert [s.version for s in snapshots] == [3, 2, 1]
    assert snapshots[0].dimensions["trust"] == pytest.approx(0.6)
    assert snapshots[0].stage == "friend"
    assert snapshots[0].conflict_status == "none"
    assert snapshots[0].trigger == "manual"


def test_snapshot_dimensions_roundtrip(session_factory):
    state = RelationshipState(
        trust=0.7, intimacy=0.6, comfort=0.8, respect=0.7, tension=0.2, version=9
    )
    created = repo.create_snapshot("u1", state.version, state, trigger="stage_up")
    assert created.dimensions == {
        "intimacy": 0.6,
        "trust": 0.7,
        "familiarity": 0.3,
        "respect": 0.7,
        "comfort": 0.8,
        "tension": 0.2,
    }
    assert created.trigger == "stage_up"


def test_get_latest_before_returns_anchor(session_factory):
    repo.create_snapshot("u1", 1, _state(1, 0.4))
    repo.create_snapshot("u1", 5, _state(5, 0.6))
    anchor = repo.get_latest_before("u1", 7)
    assert anchor is not None and anchor.version == 5
    assert repo.get_latest_before("u1", 4).version == 1
    assert repo.get_latest_before("u1", 0) is None


def test_retention_keeps_latest_windows(session_factory, monkeypatch):
    class _Settings:
        rel_snapshot_keep = 3

    monkeypatch.setattr(repo, "get_settings", lambda: _Settings())
    for version in range(1, 6):
        repo.create_snapshot("u1", version, _state(version, 0.3))
    versions = [s.version for s in repo.list_snapshots("u1")]
    assert versions == [5, 4, 3]
    assert repo.get_earliest_version("u1") == 3


def test_users_isolated(session_factory):
    repo.create_snapshot("u1", 1, _state(1, 0.4))
    assert repo.list_snapshots("u2") == []
    assert repo.get_earliest_version("u2") is None