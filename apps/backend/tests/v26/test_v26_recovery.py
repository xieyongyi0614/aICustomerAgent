"""V2.6.1 REF-006：孤儿 executing 恢复 + partial 终态映射。"""

from datetime import datetime, timedelta

from app.core import timeutil
from app.application import action_engine
from app.core.settings import get_settings
from app.models.action import ActionResult, ActionRecord
from app.repositories import action_repository


def _record(
    user_id: str,
    status: str,
    *,
    updated_at: datetime | None = None,
    attempt: int = 1,
    action_type: str = "create_reminder",
) -> ActionRecord:
    now = timeutil.now()
    return ActionRecord(
        id=action_repository.new_record_id(),
        user_id=user_id,
        action_type=action_type,
        status=status,
        source="conversation",
        dedupe_key=f"rec_{user_id}_{now.timestamp()}",
        intent={"action_type": action_type, "confidence": "confident"},
        params={"content": "恢复", "due_at": now.isoformat()},
        attempt=attempt,
        created_at=now,
        updated_at=updated_at or now,
        executed_at=now,
    )


class TestStaleExecutingRecovery:
    def test_repository_list_stale_executing(self):
        stale_at = timeutil.now() - timedelta(hours=2)
        fresh_at = timeutil.now()
        stale = action_repository.save_record(
            _record("u_rec_a", "executing", updated_at=stale_at)
        )
        fresh = action_repository.save_record(
            _record("u_rec_b", "executing", updated_at=fresh_at)
        )
        cutoff = timeutil.now() - timedelta(minutes=30)
        found_ids = {r.id for r in action_repository.list_stale_executing(cutoff, limit=50)}
        assert stale.id in found_ids
        assert fresh.id not in found_ids

    def test_recover_stale_executing_to_failed(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_executing_timeout_minutes", 30)
        stale_at = timeutil.now() - timedelta(hours=1)
        record = action_repository.save_record(
            _record("u_rec_c", "executing", updated_at=stale_at, attempt=1)
        )
        recovered = action_engine._recover_stale_executing()
        assert recovered >= 1
        loaded = action_repository.get_record(record.id)
        assert loaded is not None
        assert loaded.status == "failed"
        assert loaded.gate_reason == "timeout"

    def test_recover_skips_fresh_executing(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_executing_timeout_minutes", 30)
        record = action_repository.save_record(_record("u_rec_d", "executing"))
        action_engine._recover_stale_executing()
        loaded = action_repository.get_record(record.id)
        assert loaded is not None
        assert loaded.status == "executing"

    def test_expire_planned_includes_recovery(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_executing_timeout_minutes", 30)
        stale_at = timeutil.now() - timedelta(hours=1)
        record = action_repository.save_record(
            _record("u_rec_f", "executing", updated_at=stale_at)
        )
        action_engine._expire_planned()
        loaded = action_repository.get_record(record.id)
        assert loaded is not None
        assert loaded.status == "failed"
        assert loaded.gate_reason == "timeout"


class TestPartialTerminalMapping:
    def test_partial_maps_to_failed_not_executing(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_retry_max_attempts", 2)
        record = _record("u_partial", "executing")
        result = ActionResult(status="partial", failure_kind="transient")
        action_engine._apply_action_result_to_record(record, result, settings)
        assert record.status == "failed"
        assert record.gate_reason in ("transient", "partial")

    def test_count_active_excludes_recovered(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "action_executing_timeout_minutes", 30)
        user_id = "u_rec_count"
        stale_at = timeutil.now() - timedelta(hours=1)
        record = action_repository.save_record(
            _record(user_id, "executing", updated_at=stale_at)
        )
        before = action_repository.count_active(user_id)
        assert before >= 1
        action_engine._recover_stale_executing()
        after = action_repository.count_active(user_id)
        assert after < before
        loaded = action_repository.get_record(record.id)
        assert loaded is not None
        assert loaded.status == "failed"
