"""V9-004 action 仓储集成测试（persistence + alembic 往返 + 保留清理）。"""

from datetime import datetime, timedelta

from app.models.action import ActionRecord
from app.repositories import action_repository


def _record(user_id="u1", action_type="create_reminder", status="created", dedupe="k1", id=None) -> ActionRecord:
    now = datetime.now()
    return ActionRecord(
        id=id or action_repository.new_record_id(),
        user_id=user_id,
        action_type=action_type,
        status=status,
        dedupe_key=dedupe,
        intent={"action_type": action_type, "confidence": "confident"},
        params={"content": "开会", "due_at": "2026-09-04T08:00:00"},
        created_at=now,
        updated_at=now,
    )


def test_save_and_get_roundtrip():
    record = _record()
    saved = action_repository.save_record(record)
    loaded = action_repository.get_record(saved.id)
    assert loaded is not None
    assert loaded.action_type == "create_reminder"
    assert loaded.params["content"] == "开会"
    assert loaded.status == "created"


def test_update_record():
    record = action_repository.save_record(_record())
    record.status = "succeeded"
    record.result = {"status": "succeeded", "effects": []}
    action_repository.save_record(record)
    loaded = action_repository.get_record(record.id)
    assert loaded.status == "succeeded"
    assert loaded.result["status"] == "succeeded"


def test_list_by_status_and_user():
    action_repository.save_record(_record(status="succeeded"))
    action_repository.save_record(_record(status="failed", dedupe="k2"))
    action_repository.save_record(_record(user_id="u2", dedupe="k3"))
    succeeded = action_repository.list_records("u1", status="succeeded")
    assert len(succeeded) == 1
    assert succeeded[0].status == "succeeded"
    by_status = action_repository.list_by_status("failed")
    assert len(by_status) == 1


def test_list_by_dedupe_and_count_active():
    action_repository.save_record(_record(dedupe="dup", status="created"))
    action_repository.save_record(_record(dedupe="dup", status="succeeded"))
    now = datetime.now()
    dup = action_repository.list_by_dedupe("u1", "dup", now - timedelta(days=1))
    assert len(dup) == 2
    active = action_repository.count_active("u1")
    assert active == 1


def test_list_retryable():
    now = datetime.now()
    rec = _record(status="executing")
    rec.next_retry_at = now - timedelta(seconds=5)
    action_repository.save_record(rec)
    retryable = action_repository.list_retryable(now)
    assert len(retryable) == 1
    assert retryable[0].id == rec.id


def test_retain_cleanup():
    old = _record(dedupe="kold")
    old.created_at = datetime.now() - timedelta(days=365)
    action_repository.save_record(old)
    fresh = _record(dedupe="knew")
    action_repository.save_record(fresh)
    removed = action_repository.retain_cleanup()
    assert removed >= 1
    assert action_repository.get_record(fresh.id) is not None