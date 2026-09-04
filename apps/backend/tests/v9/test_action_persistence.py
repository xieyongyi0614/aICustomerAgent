"""V9 Action Persistence：action_records 仓储 CRUD / 幂等 / 保留清理（V9-004）。"""

from datetime import datetime, timedelta

import pytest

from app.application.action_engine import new_record, run_action_planning
from app.models.action import ActionIntent
from app.repositories import action_repository
from app.core.settings import get_settings


def _intent(action_type="create_reminder", **params):
    return ActionIntent(action_type=action_type, confidence="confident", params=params, dedupe_key="")


def test_save_and_get_roundtrip(db_session_factory):
    intent = _intent(content="喝水", due_at="20:00")
    record = new_record(intent, "persist-user", session_id="s1")
    action_repository.save_record(record)
    got = action_repository.get_record(record.id)
    assert got is not None
    assert got.action_type == "create_reminder"
    assert got.params["content"] == "喝水"


def test_dedupe_key_location(db_session_factory):
    intent = ActionIntent(
        action_type="remember_fact",
        confidence="confident",
        params={"fact": "喜欢猫"},
        dedupe_key="dedupe-1",
    )
    record = new_record(intent, "persist-user-2", session_id=None)
    action_repository.save_record(record)
    records = action_repository.list_by_dedupe(
        "persist-user-2", "dedupe-1", since=datetime.now() - timedelta(hours=24)
    )
    assert any(r.id == record.id for r in records)


def test_retention_cleanup_removes_old(db_session_factory):
    intent = _intent(content="old")
    record = new_record(intent, "persist-user-3", session_id=None)
    record.created_at = datetime.now() - timedelta(days=400)
    action_repository.save_record(record)
    action_repository.retain_cleanup()
    assert action_repository.get_record(record.id) is None


@pytest.mark.asyncio
async def test_list_records_newest_first(db_session_factory, override_settings):
    override_settings(action_enabled=True)
    for i in range(3):
        await run_action_planning("persist-user-4", _intent(content=f"任务{i}"), session_id=None)
    records = action_repository.list_records("persist-user-4", limit=10)
    assert len(records) >= 3
    times = [r.created_at for r in records[:3]]
    assert times == sorted(times, reverse=True)
