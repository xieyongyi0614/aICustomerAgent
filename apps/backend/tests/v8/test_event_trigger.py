"""V8-008 Event Trigger Test（testing.md §2）：事件触发与完结幂等。"""

from datetime import datetime, timedelta

import pytest

from app.application import world_engine
from app.models.world import EventStatus
from app.repositories import world_repository


def _world_id():
    return world_repository.world_id_for("default-user")


async def _await_until(predicate, timeout=3.0):
    import asyncio
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


@pytest.mark.asyncio
async def test_event_full_lifecycle_via_chat(db_session_factory, fake_llm, llm_override, override_settings):
    override_settings(world_time_mode="simulated")
    llm = fake_llm(response=["好耶"], structured_responses={})
    llm_override(llm)
    from app.services import agent_service

    async def _turn(content):
        events = []
        async for event in agent_service.stream_chat("s-v8-event", "default-user", content, llm=llm):
            events.append(event)
        return events

    events = await _turn("明天我要面试，好紧张")
    assert events[-1]["kind"] == "done"
    assert await _await_until(
        lambda: [
            event
            for event in world_repository.list_events(_world_id(), statuses=["scheduled"])
            if event.type == "interview"
        ]
    )
    scheduled = world_repository.list_events(_world_id(), statuses=["scheduled"])
    assert any(event.type == "interview" for event in scheduled)

    await _turn("面试终于结束了")
    assert await _await_until(
        lambda: any(
            event.status is EventStatus.COMPLETED
            for event in world_repository.list_events(
                _world_id(), statuses=["completed"]
            )
            if event.type == "interview"
        )
    )


@pytest.mark.asyncio
async def test_due_trigger_is_idempotent(db_session_factory, override_settings):
    override_settings(world_time_mode="simulated")
    world_engine.ensure_world("default-user")
    now = world_engine._default_provider.now(world_engine.get_world("default-user"))
    event = world_engine.create_event(
        "default-user",
        event_type="interview",
        title="用户的面试",
        importance="high",
        due_at=now - timedelta(hours=1),
        source="manual",
    )
    assert event is not None
    assert world_engine.trigger_due_events("default-user", now) == 1
    assert world_engine.trigger_due_events("default-user", now) == 0
    loaded = world_repository.get_event(_world_id(), event.id)
    assert loaded.status is EventStatus.ACTIVE
    assert loaded.started_at is not None


@pytest.mark.asyncio
async def test_maintenance_triggers_due_and_prunes(db_session_factory, override_settings):
    override_settings(world_time_mode="simulated", world_event_retention_days=90)
    world_engine.ensure_world("default-user")
    now = world_engine._default_provider.now(world_engine.get_world("default-user"))
    world_engine.create_event(
        "default-user",
        event_type="interview",
        title="用户的面试",
        importance="high",
        due_at=now - timedelta(hours=2),
        source="manual",
    )
    old = world_engine.create_event(
        "default-user",
        event_type="appointment",
        title="旧预约",
        importance="low",
        source="manual",
    )
    completed = world_repository.get_event(_world_id(), old.id)
    completed.status = EventStatus.COMPLETED
    completed.completed_at = now - timedelta(days=120)
    world_repository.save_event(completed)

    assert world_engine.run_maintenance("default-user") >= 2
    loaded = world_repository.get_event(_world_id(), old.id)
    assert loaded is None, "超过保留期的完结事件应被清理"
    active = world_repository.list_events(
        _world_id(), statuses=["scheduled", "active"]
    )
    assert any(event.status is EventStatus.ACTIVE for event in active)
