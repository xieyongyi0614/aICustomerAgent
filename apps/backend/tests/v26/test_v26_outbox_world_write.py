"""V2.6.1 REF-001 T2：Flag on + outbox 世界写端到端（world_ops 非空 → 消费后事件）。"""

import asyncio
from datetime import datetime, timedelta

from app.application import outbox_consumer, world_engine
from app.repositories import action_repository, outbox_repository, world_repository
from app.services.action import manager
from app.repositories import action_repository, outbox_repository, world_repository
from app.services.action import manager


def _due_at(hours: int = 3) -> str:
    return (datetime.now() + timedelta(hours=hours)).isoformat()


class TestOutboxWorldWrite:
    def test_create_reminder_outbox_world_ops_and_consume(self, override_settings):
        override_settings(
            action_outbox_enabled=True,
            world_enabled=True,
        )
        world_engine.ensure_world("u_t2_outbox")
        action = manager.create(
            user_id="u_t2_outbox",
            action_type="create_reminder",
            params={"content": "T2 提醒学习", "due_at": _due_at()},
        )
        result = asyncio.run(manager.execute(action.id))
        assert result is not None
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"

        step = loaded.steps[0]
        step_result = step.get("result") or {}
        payload = step_result.get("payload") or {}
        assert payload.get("deferred_world_op"), "旧读键 payload 必须带 deferred_world_op"
        assert step_result.get("output", {}).get("deferred_world_op")

        row = outbox_repository.get(action.id)
        assert row is not None
        assert row.status == "pending"
        world_ops = row.payload.get("world_ops") or []
        assert world_ops, "outbox world_ops 不能为空"
        assert world_ops[0].get("op") == "create_event"

        stats = outbox_consumer.consume_pending()
        assert stats["consumed"] >= 1
        consumed = outbox_repository.get(action.id)
        assert consumed is not None
        assert consumed.status == "consumed"

        world = world_engine.ensure_world("u_t2_outbox")
        events = world_repository.list_events(world.world_id, limit=50, types=["reminder"])
        matched = [e for e in events if e.payload.get("outbox_action_id") == action.id]
        assert len(matched) == 1, "同一 Action 世界事件应恰好 1 行"

    def test_outbox_off_direct_world_event(self, override_settings):
        override_settings(
            action_outbox_enabled=False,
            world_enabled=True,
        )
        world_engine.ensure_world("u_t2_direct")
        action = manager.create(
            user_id="u_t2_direct",
            action_type="create_reminder",
            params={"content": "T2 直写提醒", "due_at": _due_at()},
        )
        result = asyncio.run(manager.execute(action.id))
        assert result is not None
        loaded = action_repository.get_record(action.id)
        assert loaded is not None
        assert loaded.status == "succeeded"
        assert outbox_repository.get(action.id) is None

        step_result = (loaded.steps[0] or {}).get("result") or {}
        payload = step_result.get("payload") or {}
        world_event_id = payload.get("world_event_id") or (
            step_result.get("output") or {}
        ).get("world_event_id")
        assert world_event_id, "直写路径必须回填 world_event_id 到旧读键"
