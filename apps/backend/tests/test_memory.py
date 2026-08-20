from unittest.mock import AsyncMock, patch

from app.services import memory_service
from app.repositories import memory_repository as repo


async def _decision(**kwargs):
    defaults = {
        "should_save": False,
        "memory": None,
        "memory_type": "preference",
        "importance": 0.0,
    }
    defaults.update(kwargs)
    return type("Decision", (), defaults)()


async def test_extract_and_save_persists(db_session_factory):
    decision = await _decision(
        should_save=True, memory="用户喜欢寿司", memory_type="preference", importance=0.8
    )
    with patch("app.services.memory_service.extract", AsyncMock(return_value=decision)):
        await memory_service.extract_and_save("u1", "我喜欢寿司", "好的")
    assert any(m.memory == "用户喜欢寿司" for m in repo.list_by_user("u1"))


async def test_low_importance_filtered(db_session_factory):
    decision = await _decision(
        should_save=True, memory="用户喜欢吃咖喱", memory_type="preference", importance=0.5
    )
    with patch("app.services.memory_service.extract", AsyncMock(return_value=decision)):
        await memory_service.extract_and_save("u1", "咖喱", "好的")
    assert repo.list_by_user("u1") == []


async def test_should_save_false_skipped(db_session_factory):
    with patch("app.services.memory_service.extract", AsyncMock(return_value=await _decision())):
        await memory_service.extract_and_save("u1", "今天吃了拉面", "嗯")
    assert repo.list_by_user("u1") == []


async def test_duplicate_not_inserted_twice(db_session_factory):
    decision = await _decision(
        should_save=True, memory="用户喜欢寿司", memory_type="preference", importance=0.8
    )
    with patch("app.services.memory_service.extract", AsyncMock(return_value=decision)):
        await memory_service.extract_and_save("u1", "a", "b")
        await memory_service.extract_and_save("u1", "a", "b")
    assert len(repo.list_by_user("u1")) == 1


async def test_retrieve_hits_matching_memory(db_session_factory):
    repo.create_memory("u1", "用户喜欢寿司", "preference", 0.8)
    repo.create_memory("u1", "用户在学 Python", "goal", 0.7)
    hits = memory_service.retrieve("u1", "我想吃寿司", top_k=5)
    assert any(m.memory == "用户喜欢寿司" for m in hits)


async def test_retrieve_empty_result(db_session_factory):
    repo.create_memory("u1", "用户喜欢寿司", "preference", 0.8)
    assert memory_service.retrieve("u1", "完全不相关的 zzz", top_k=5) == []


async def test_extract_failure_skipped(db_session_factory):
    with patch("app.services.memory_service.extract", AsyncMock(side_effect=RuntimeError("boom"))):
        await memory_service.extract_and_save("u1", "x", "y")
    assert repo.list_by_user("u1") == []
