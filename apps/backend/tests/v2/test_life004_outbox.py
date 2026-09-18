"""LIFE-004 Outbox 一致性测试。

覆盖：E-LIFE-04 幂等重放（outbox/world_event 恒 1）、同事务落库、
崩溃重放按 applied_ops 进度续走、退避死信、能力 deferral（Flag ON 不直写）、
Flag OFF 逐字节 v1、debug actions outbox 字段。
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app.application import outbox_consumer, world_engine
from app.application.action_engine import integrate_result
from app.models.action import ActionRecord, ActionResult
from app.repositories import (
    action_repository,
    outbox_repository,
    world_repository,
)
from app.services.action.capabilities.reminder import ReminderCapability
from app.services.action.registry import ExecutionContext

NOW = datetime(2026, 9, 7, 12, 0, 0)
USER = "outbox-user"


@pytest.fixture()
def outbox_on(override_settings):
    override_settings(
        ACTION_OUTBOX_ENABLED="true",
        world_enabled="true",
        action_enabled="true",
    )
    yield


def _make_succeeded_record(record_id="act-1", with_deferred_op=True) -> ActionRecord:
    steps = []
    if with_deferred_op:
        steps = [
            {
                "step": "create_reminder",
                "status": "succeeded",
                "result": {
                    "status": "succeeded",
                    "payload": {
                        "deferred_world_op": {
                            "op": "create_event",
                            "args": [
                                USER,
                                "reminder",
                                "复查",
                                "high",
                                (NOW + timedelta(hours=2)).isoformat(),
                                "autonomy",
                            ],
                        },
                        "failure_kind": None,
                    },
                },
            }
        ]
    return ActionRecord(
        id=record_id,
        user_id=USER,
        action_type="create_reminder",
        intent={"action_type": "create_reminder", "confidence": "confident", "params": {"content": "复查"}},
        dedupe_key=f"dk-{record_id}",
        params={"content": "复查"},
        status="succeeded",
        steps=steps,
        result=ActionResult(status="succeeded", effects=[]).model_dump(mode="json"),
        created_at=NOW,
        updated_at=NOW,
    )


def _world_event_titles(user_id: str) -> list[str]:
    world = world_engine.ensure_world(user_id)
    return [
        e.title
        for e in world_repository.list_events(world.world_id, limit=50)
    ]


class TestIntegrateOutbox:
    def test_flag_on_same_transaction_write(self, db_session_factory, outbox_on):
        record = _make_succeeded_record()
        integrate_result(record, ActionResult(status="succeeded", effects=[]))

        row = outbox_repository.get(record.id)
        assert row is not None and row.status == "pending"
        assert row.payload["world_ops"][0]["op"] == "create_event"
        assert row.payload["record"]["id"] == record.id
        saved = action_repository.get_record(record.id)
        assert saved is not None and saved.status == "succeeded"

    def test_replay_three_times_single_outbox_row(
        self, db_session_factory, outbox_on
    ):
        record = _make_succeeded_record()
        for _ in range(3):
            integrate_result(record, ActionResult(status="succeeded", effects=[]))
        rows = [
            r for r in outbox_repository.list_recent() if r.idempotency_key == record.id
        ]
        assert len(rows) == 1

    def test_flag_off_no_outbox_row(self, db_session_factory):
        record = _make_succeeded_record()
        integrate_result(record, ActionResult(status="succeeded", effects=[]))
        assert outbox_repository.get(record.id) is None
        assert action_repository.get_record(record.id) is not None


class TestConsumer:
    def test_consume_applies_world_op_and_marks_consumed(
        self, db_session_factory, outbox_on
    ):
        record = _make_succeeded_record()
        integrate_result(record, ActionResult(status="succeeded", effects=[]))

        stats = outbox_consumer.consume_pending(now=NOW)
        assert stats["consumed"] == 1
        row = outbox_repository.get(record.id)
        assert row.status == "consumed"
        titles = _world_event_titles(USER)
        assert "复查" in titles
        world = world_engine.ensure_world(USER)
        event = next(
            e
            for e in world_repository.list_events(world.world_id, limit=50)
            if e.title == "复查"
        )
        assert event.payload.get("outbox_action_id") == record.id

    def test_replay_consume_does_not_duplicate_world_event(
        self, db_session_factory, outbox_on
    ):
        """同一 Action 结果重放三次：world_event 恒 1（E-LIFE-04）。"""
        record = _make_succeeded_record()
        integrate_result(record, ActionResult(status="succeeded", effects=[]))
        outbox_consumer.consume_pending(now=NOW)

        # 重放：重新登记同键行不可行（唯一键），改为直接重置消费状态模拟重放
        from app.core.db import OutboxEventRow

        with outbox_repository.SessionLocal() as session:
            session.query(OutboxEventRow).filter(
                OutboxEventRow.idempotency_key == record.id
            ).update({"status": "pending", "attempts": 0})
            session.commit()
        for _ in range(2):
            outbox_consumer.consume_pending(now=NOW + timedelta(seconds=1))
        titles = [t for t in _world_event_titles(USER) if t == "复查"]
        assert titles == ["复查"]

    def test_crash_replay_resumes_by_progress_marker(
        self, db_session_factory, outbox_on
    ):
        """world op 落库后崩溃（未 CAS consumed）：重启重放按进度续走不重放。"""
        ops = [
            {"op": "create_event", "args": [USER, "reminder", "事项一", "high", (NOW + timedelta(hours=1)).isoformat(), "autonomy"]},
            {"op": "create_event", "args": [USER, "reminder", "事项二", "high", (NOW + timedelta(hours=2)).isoformat(), "autonomy"]},
        ]
        key = f"act-crash-{uuid.uuid4().hex[:8]}"
        outbox_repository.insert(
            {
                "action_id": key,
                "user_id": USER,
                "record": _make_succeeded_record(key).model_dump(mode="json"),
                "world_ops": ops,
            },
            idempotency_key=key,
            now=NOW,
        )
        # 模拟第一 op 落库后崩溃：真实执行 op1 + 进度标记已持久化，但未 consumed
        outbox_consumer._apply_world_op(key, ops[0])
        outbox_repository.advance_progress(key, 1)

        stats = outbox_consumer.consume_pending(now=NOW)
        assert stats["consumed"] == 1
        titles = _world_event_titles(USER)
        assert "事项一" in titles and "事项二" in titles
        assert titles.count("事项一") == 1 and titles.count("事项二") == 1

    def test_retry_backoff_then_dead_letter(
        self, db_session_factory, outbox_on, monkeypatch, override_settings
    ):
        override_settings(life_loop_outbox_max_attempts="3")

        def boom(*args, **kwargs):
            raise RuntimeError("world down")

        monkeypatch.setattr(world_engine, "create_event", boom)
        record = _make_succeeded_record("act-dl")
        integrate_result(record, ActionResult(status="succeeded", effects=[]))

        stats1 = outbox_consumer.consume_pending(now=NOW)
        assert stats1["retried"] == 1
        row = outbox_repository.get(record.id)
        assert row.status == "pending" and row.attempts == 1
        assert row.next_retry_at is not None

        # 退避未到 → 不扫描
        stats_skip = outbox_consumer.consume_pending(now=NOW + timedelta(seconds=1))
        assert stats_skip["scanned"] == 0

        # 连续失败达上限 → failed 死信
        for i in range(2, 4):
            stats_i = outbox_consumer.consume_pending(
                now=NOW + timedelta(hours=i)
            )
        row = outbox_repository.get(record.id)
        assert row.status == "failed"
        assert row.attempts == 3
        assert "world down" in (row.last_error or "")


class TestCapabilityDeferral:
    @pytest.mark.asyncio
    async def test_reminder_deferred_no_direct_write(
        self, db_session_factory, outbox_on
    ):
        ctx = ExecutionContext(user_id=USER, settings=None)
        capability = ReminderCapability()
        result = await capability.execute(
            "create",
            {"content": "复查", "due_at": (NOW + timedelta(hours=1)).isoformat()},
            ctx,
        )
        assert result.status == "succeeded"
        assert result.payload["deferred_world_op"]["op"] == "create_event"
        assert "复查" not in _world_event_titles(USER)

    @pytest.mark.asyncio
    async def test_reminder_flag_off_direct_write(self, db_session_factory):
        world_engine.ensure_world(USER)
        ctx = ExecutionContext(user_id=USER, settings=None)
        capability = ReminderCapability()
        result = await capability.execute(
            "create",
            {"content": "直写", "due_at": (NOW + timedelta(hours=1)).isoformat()},
            ctx,
        )
        assert result.status == "succeeded"
        assert result.payload.get("world_event_id")
        assert "直写" in _world_event_titles(USER)


class TestDebugOutbox:
    def test_get_action_attaches_outbox_status(self, db_session_factory, outbox_on):
        from app.api.v1.action import get_action

        record = _make_succeeded_record("act-dbg")
        integrate_result(record, ActionResult(status="succeeded", effects=[]))
        data = get_action(record.id)
        assert data["outbox"] is not None
        assert data["outbox"]["status"] == "pending"
        assert data["outbox"]["attempts"] == 0

        outbox_consumer.consume_pending(now=NOW)
        data = get_action(record.id)
        assert data["outbox"]["status"] == "consumed"
