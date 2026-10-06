"""V8.5 relationship_conflicts 仓储集成测试（conflict-system.md §4）。"""

from datetime import datetime, timedelta

import pytest

from app.core import timeutil
from app.models.relationship import ConflictRecord
from app.repositories import relationship_conflict_repository as repo

NOW = timeutil.ensure_aware(datetime(2026, 8, 31, 12, 0, 0))


def _record(status="conflict", **overrides) -> ConflictRecord:
    values = dict(
        user_id="u1",
        status=status,
        started_at=NOW - timedelta(hours=2),
        last_negative_at=NOW - timedelta(hours=1),
        created_at=NOW - timedelta(hours=2),
    )
    values.update(overrides)
    return ConflictRecord(**values)


def test_create_and_get_active_conflict(db_session_factory):
    created = repo.create_conflict(_record())
    assert created.id is not None
    active = repo.get_active_conflict("u1")
    assert active is not None
    assert active.status == "conflict"
    assert active.last_negative_at == NOW - timedelta(hours=1)


def test_resolved_row_not_active_but_listed(db_session_factory):
    record = repo.create_conflict(_record())
    record.status = "resolved"
    record.resolved_at = NOW
    record.resolution = "reconciled"
    repo.update_status(record)
    assert repo.get_active_conflict("u1") is None
    listed = repo.list_conflicts("u1")
    assert len(listed) == 1
    assert listed[0].status == "resolved"
    assert listed[0].resolution == "reconciled"


def test_update_status_mutates_same_row(db_session_factory):
    created = repo.create_conflict(_record())
    created.status = "cold"
    created.recovery_started_at = None
    updated = repo.update_status(created)
    assert updated.id == created.id
    assert updated.status == "cold"
    conflicts = repo.list_conflicts("u1")
    assert len(conflicts) == 1
    assert conflicts[0].status == "cold"


def test_update_missing_record_creates(db_session_factory):
    ghost = _record(status="strain")
    result = repo.update_status(ghost)
    assert result.id == ghost.id
    assert repo.get_active_conflict("u1").status == "strain"


def test_users_isolated_and_ordering(db_session_factory):
    older = repo.create_conflict(
        _record(user_id="u2", started_at=NOW - timedelta(days=2), created_at=NOW - timedelta(days=2))
    )
    newer = repo.create_conflict(
        _record(user_id="u2", started_at=NOW - timedelta(hours=1), created_at=NOW - timedelta(hours=1))
    )
    listed = repo.list_conflicts("u2")
    assert [c.id for c in listed] == [newer.id, older.id]
    assert repo.get_active_conflict("u1") is None