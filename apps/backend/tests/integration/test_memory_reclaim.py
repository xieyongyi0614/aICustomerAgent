from datetime import datetime, timedelta

from app.repositories import memory_repository as repo
from app.services import memory_service


async def test_expired_active_memory_reclaimed(db_session_factory):
    expired = repo.create_memory(
        "u1",
        "asuna",
        "临时信息",
        "user_fact",
        0.5,
        0.9,
        expires_at=datetime.now() - timedelta(hours=1),
    )
    valid = repo.create_memory(
        "u1",
        "asuna",
        "长期事实",
        "user_fact",
        0.8,
        0.9,
        expires_at=datetime.now() + timedelta(days=7),
    )
    no_expiry = repo.create_memory(
        "u1", "asuna", "永久事实", "user_fact", 0.8, 0.9
    )
    reclaimed = memory_service.reclaim_expired_memories()
    assert reclaimed == 1
    assert repo.get_memory(expired.id).status == "invalidated"
    assert repo.get_memory(valid.id).status == "active"
    assert repo.get_memory(no_expiry.id).status == "active"


async def test_time_injected_reclaim(db_session_factory):
    expired_at = datetime.now() - timedelta(days=2)
    memory = repo.create_memory(
        "u1", "asuna", "已过期事实", "user_fact", 0.5, 0.9, expires_at=expired_at
    )
    reclaimed = memory_service.reclaim_expired_memories(
        now=datetime.now() + timedelta(days=1)
    )
    assert reclaimed == 1
    assert repo.get_memory(memory.id).status == "invalidated"


async def test_already_invalidated_not_reclaimed_again(db_session_factory):
    memory = repo.create_memory(
        "u1", "asuna", "过期旧记忆", "user_fact", 0.5, 0.9
    )
    repo.invalidate_memory(memory.id)
    assert memory_service.reclaim_expired_memories() == 0


async def test_reclaim_loop_runs_and_cancellable(db_session_factory, monkeypatch):
    import asyncio

    calls = {"n": 0}
    original = memory_service.reclaim_expired_memories

    def counting():
        calls["n"] += 1
        return original()

    monkeypatch.setattr(memory_service, "reclaim_expired_memories", counting)
    task = asyncio.create_task(memory_service.run_memory_reclaim_loop(interval_seconds=0))
    await asyncio.sleep(0.15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert calls["n"] >= 2
