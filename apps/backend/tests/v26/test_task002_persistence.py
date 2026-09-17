"""TASK-002 Action Persistence Layer 集成测试。"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.db import ActionScheduleRow, ActionRecordRow
from app.models.action import ActionEffect, ActionRecord, ActionResult, ActionSchedule
from app.repositories import action_repository


def _record(
    user_id="u1",
    action_type="create_reminder",
    status="created",
    dedupe="k1",
    source="conversation",
    priority=100,
) -> ActionRecord:
    now = datetime.now()
    return ActionRecord(
        id=action_repository.new_record_id(),
        user_id=user_id,
        action_type=action_type,
        status=status,
        source=source,
        priority=priority,
        dedupe_key=dedupe,
        intent={"action_type": action_type, "confidence": "confident"},
        params={"content": "开会", "due_at": "2026-09-04T08:00:00"},
        created_at=now,
        updated_at=now,
    )


def _schedule(action_id: str, when_type="delay", status="scheduled", offset_minutes=30) -> ActionSchedule:
    now = datetime.now()
    return ActionSchedule(
        id=action_repository.new_schedule_id(),
        action_id=action_id,
        when_type=when_type,
        scheduled_at=now + timedelta(minutes=offset_minutes),
        priority=100,
        status=status,
        created_at=now,
        updated_at=now,
    )


class TestPriorityColumn:
    def test_default_priority_roundtrip(self):
        saved = action_repository.save_record(_record(priority=100))
        loaded = action_repository.get_record(saved.id)
        assert loaded is not None
        assert loaded.priority == 100

    def test_custom_priority_persists(self):
        saved = action_repository.save_record(_record(priority=200, dedupe="p1"))
        loaded = action_repository.get_record(saved.id)
        assert loaded is not None
        assert loaded.priority == 200

    def test_priority_update_persists(self):
        record = action_repository.save_record(_record(dedupe="p2"))
        record.priority = 50
        action_repository.save_record(record)
        loaded = action_repository.get_record(record.id)
        assert loaded is not None
        assert loaded.priority == 50


class TestResultRoundtrip:
    def test_action_result_json_roundtrip(self):
        result = ActionResult(
            status="succeeded",
            effects=[ActionEffect(kind="world", ref="evt_1", detail="ok")],
            error=None,
            failure_kind=None,
        )
        record = _record(dedupe="r1", status="succeeded")
        record.result = result.model_dump()
        saved = action_repository.save_record(record)
        loaded = action_repository.get_record(saved.id)
        assert loaded is not None
        restored = ActionResult.model_validate(loaded.result)
        assert restored.status == "succeeded"
        assert restored.effects[0].ref == "evt_1"


class TestSourceFiveValues:
    def test_plan_source_persists(self):
        saved = action_repository.save_record(_record(source="plan", dedupe="s1"))
        loaded = action_repository.get_record(saved.id)
        assert loaded is not None
        assert loaded.source == "plan"

    def test_event_driven_source_persists(self):
        saved = action_repository.save_record(
            _record(source="event_driven", dedupe="s2")
        )
        loaded = action_repository.get_record(saved.id)
        assert loaded is not None
        assert loaded.source == "event_driven"


class TestScheduleRepository:
    def test_save_get_roundtrip(self):
        action_repository.save_record(_record(dedupe="a1"))
        record = action_repository.list_by_dedupe(
            "u1", "a1", datetime.now() - timedelta(days=1)
        )[0]
        schedule = action_repository.save_schedule(_schedule(record.id))
        loaded = action_repository.get_schedule(record.id)
        assert loaded is not None
        assert loaded.id == schedule.id
        assert loaded.action_id == record.id
        assert loaded.when_type == "delay"
        assert loaded.status == "scheduled"
        assert loaded.priority == 100

    def test_duplicate_action_id_rejected(self):
        action_repository.save_record(_record(dedupe="a2"))
        record = action_repository.list_by_dedupe(
            "u1", "a2", datetime.now() - timedelta(days=1)
        )[0]
        action_repository.save_schedule(_schedule(record.id))
        with pytest.raises(IntegrityError):
            action_repository.save_schedule(
                ActionSchedule(
                    id=action_repository.new_schedule_id(),
                    action_id=record.id,
                    when_type="delay",
                    scheduled_at=datetime.now(),
                )
            )

    def test_list_due_schedules(self):
        now = datetime.now()
        for i, offset in enumerate((-10, 60)):
            action_repository.save_record(_record(dedupe=f"d{i}"))
            record = action_repository.list_by_dedupe(
                "u1", f"d{i}", now - timedelta(days=1)
            )[0]
            action_repository.save_schedule(
                _schedule(record.id, offset_minutes=offset)
            )
        due = action_repository.list_due_schedules(now)
        assert len(due) == 1
        assert due[0].when_type == "delay"

    def test_mark_executed_and_cancelled(self):
        action_repository.save_record(_record(dedupe="m1"))
        record = action_repository.list_by_dedupe(
            "u1", "m1", datetime.now() - timedelta(days=1)
        )[0]
        action_repository.save_schedule(_schedule(record.id))
        executed = action_repository.mark_schedule_executed(record.id)
        assert executed is not None
        assert executed.status == "executed"

        action_repository.save_record(_record(dedupe="m2"))
        record2 = action_repository.list_by_dedupe(
            "u1", "m2", datetime.now() - timedelta(days=1)
        )[0]
        action_repository.save_schedule(_schedule(record2.id))
        cancelled = action_repository.mark_schedule_cancelled(record2.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"

    def test_immediate_cron_types(self):
        action_repository.save_record(_record(dedupe="w1"))
        record = action_repository.list_by_dedupe(
            "u1", "w1", datetime.now() - timedelta(days=1)
        )[0]
        action_repository.save_schedule(_schedule(record.id, when_type="immediate", offset_minutes=0))
        assert action_repository.get_schedule(record.id).when_type == "immediate"

        action_repository.save_record(_record(dedupe="w2"))
        record2 = action_repository.list_by_dedupe(
            "u1", "w2", datetime.now() - timedelta(days=1)
        )[0]
        action_repository.save_schedule(_schedule(record2.id, when_type="cron"))
        assert action_repository.get_schedule(record2.id).when_type == "cron"

    def test_invalid_when_type_rejected(self):
        with pytest.raises(ValidationError):
            ActionSchedule(
                id="sch_x",
                action_id="act_x",
                when_type="weekly",
                scheduled_at=datetime.now(),
            )


class TestOrmShape:
    def test_action_schedule_row_shape(self):
        assert ActionScheduleRow.__tablename__ == "action_schedules"
        columns = {c.name for c in ActionScheduleRow.__table__.columns}
        assert columns == {
            "id",
            "action_id",
            "when_type",
            "scheduled_at",
            "priority",
            "status",
            "created_at",
            "updated_at",
        }
        constraint_names = {
            c.name for c in ActionScheduleRow.__table__.constraints if c.name
        }
        assert "uq_action_schedules_action" in constraint_names
        assert "ck_action_schedules_when_type" in constraint_names
        assert "ck_action_schedules_status" in constraint_names
        index_names = {i.name for i in ActionScheduleRow.__table__.indexes}
        assert "idx_action_schedules_due" in index_names

    def test_action_record_row_has_priority_only_new_column(self):
        columns = {c.name for c in ActionRecordRow.__table__.columns}
        assert "priority" in columns
        assert "run_id" in columns
        assert len(columns) == 23
