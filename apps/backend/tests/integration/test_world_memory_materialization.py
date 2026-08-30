"""V8-010 记忆沉淀集成：面试完结 → 记忆出现；幂等；低重要度不沉淀。"""

from datetime import datetime

from app.application import world_engine
from app.models.world import EventImportance, EventStatus
from app.repositories import memory_repository, world_repository


def test_completed_event_materializes_memory_once(db_session_factory):
    world_engine.ensure_world("default-user")
    event = world_engine.create_event(
        "default-user",
        event_type="interview",
        title="用户的面试",
        importance="high",
        source="manual",
    )
    assert event is not None
    assert world_engine.complete_events_by_type("default-user", "interview") == 1

    memories = memory_repository.list_by_user("default-user", limit=10)
    assert any("面试" in memory.content for memory in memories)
    materialized = [m for m in memories if "面试" in m.content]
    assert all(memory.source == "user_derived" for memory in materialized)

    reloaded = world_repository.get_event(world_repository.world_id_for("default-user"), event.id)
    assert reloaded.payload.get("memory_materialized") is True
    assert world_engine.complete_events_by_type("default-user", "interview") == 0
    assert world_engine.complete_events_by_type("default-user", "meeting") == 0
    memories_again = memory_repository.list_by_user("default-user", limit=20)
    assert len([m for m in memories_again if "面试" in m.content]) == 1


def test_low_importance_event_skips_memory(db_session_factory):
    world_engine.ensure_world("default-user")
    event = world_engine.create_event(
        "default-user",
        event_type="meeting",
        title="临时提醒",
        importance="low",
        source="manual",
    )
    assert world_engine.complete_events_by_type("default-user", "meeting") == 1
    memories = memory_repository.list_by_user("default-user", limit=20)
    assert not any("临时提醒" in memory.content for memory in memories)
    reloaded = world_repository.get_event(world_repository.world_id_for("default-user"), event.id)
    assert reloaded.payload.get("memory_materialized") is True
