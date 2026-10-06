"""V8-010 记忆沉淀集成：面试完结 → 候选投递 → v2 评估转正；幂等；低重要度不沉淀。

通道收敛第 3 批（台账 §5.2）：旁路不再直写 memories，同一事件无论
「旁路先 / v2 补扫先」都收敛为同一条候选 → 至多一条记忆。
"""

import asyncio
from datetime import datetime

from app.core import timeutil
from app.application import world_engine
from app.core.db import MemoryCandidateRow
from app.models.world import EventStatus
from app.repositories import memory_repository, world_repository
from app.services.memory import evaluator as memory_evaluator
from app.services.memory import ingest as memory_ingest
from app.services.world import memory_bridge as world_memory_bridge


def _candidate_rows(user_id):
    with memory_repository.SessionLocal() as session:
        return (
            session.query(MemoryCandidateRow)
            .filter(
                MemoryCandidateRow.user_id == user_id,
                MemoryCandidateRow.source_table == "world_events",
            )
            .all()
        )


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

    candidates = _candidate_rows("default-user")
    assert len(candidates) == 1
    assert candidates[0].source == "user_derived"
    reloaded_event = world_repository.get_event(
        world_repository.ensure_world("default-user").world_id, event.id
    )
    scanned = memory_ingest.ingest_from_world_event(reloaded_event, "default-user")
    assert scanned is not None and scanned.id == candidates[0].id
    asyncio.run(memory_evaluator.evaluate_pending("default-user"))

    memories = memory_repository.list_by_user("default-user", limit=10)
    assert any("面试" in memory.content for memory in memories)
    materialized = [m for m in memories if "面试" in m.content]
    assert all(memory.source == "user_derived" for memory in materialized)

    reloaded = world_repository.get_event(world_repository.ensure_world("default-user").world_id, event.id)
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
    reloaded = world_repository.get_event(world_repository.ensure_world("default-user").world_id, event.id)
    assert reloaded.payload.get("memory_materialized") is True


def test_v2_ingest_first_bypass_later_converges_to_single_memory(db_session_factory):
    """顺序 B 探针（台账 §5.2.1）：v2 补扫先摄取并转正，旁路后到仍只有一条记忆。"""
    world_engine.ensure_world("default-user")
    event = world_engine.create_event(
        "default-user",
        event_type="interview",
        title="用户的面试",
        importance="high",
        source="manual",
    )
    assert event is not None
    event.status = EventStatus.COMPLETED
    event.completed_at = datetime(2026, 9, 30, 12, 0, 0)
    event.updated_at = timeutil.now()
    world_repository.save_event(event)

    row = memory_ingest.ingest_from_world_event(event, "default-user")
    assert row is not None
    asyncio.run(memory_evaluator.evaluate_pending("default-user"))
    assert len(memory_repository.list_by_user("default-user", limit=20)) == 1

    assert world_memory_bridge.materialize_event_memory(event, "default-user") is True
    candidates = _candidate_rows("default-user")
    assert len(candidates) == 1
    assert candidates[0].source_id == event.id

    asyncio.run(memory_evaluator.evaluate_pending("default-user"))
    memories = memory_repository.list_by_user("default-user", limit=20)
    assert len([m for m in memories if "面试" in m.content]) == 1
