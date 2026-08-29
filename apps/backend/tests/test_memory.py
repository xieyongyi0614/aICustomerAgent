from app.services import memory_service
from app.repositories import memory_repository as repo
from tests.conftest import FakeLLM


def _extraction(candidates):
    return {"MemoryExtraction": {"candidates": candidates}}


def _save_candidate(content, memory_type="user_preference", importance=0.8, **overrides):
    payload = {
        "action": "save",
        "type": memory_type,
        "content": content,
        "importance": importance,
        "confidence": 0.95,
        "source": "user_stated",
    }
    payload.update(overrides)
    return payload


async def test_extract_and_save_persists(db_session_factory):
    llm = FakeLLM(
        structured_responses=_extraction([_save_candidate("用户喜欢寿司")])
    )
    await memory_service.extract_and_save("u1", "我喜欢寿司", "好的", llm=llm)
    memories = repo.list_by_user("u1")
    assert any(m.memory == "用户喜欢寿司" for m in memories)
    row = next(m for m in memories if m.memory == "用户喜欢寿司")
    assert repo.get_memory_v4(row.id).type == "user_preference"


async def test_low_importance_filtered(db_session_factory):
    llm = FakeLLM(
        structured_responses=_extraction([_save_candidate("用户喜欢吃咖喱", importance=0.4)])
    )
    await memory_service.extract_and_save("u1", "咖喱", "好的", llm=llm)
    assert repo.list_by_user("u1") == []


async def test_chitchat_saves_nothing(db_session_factory):
    llm = FakeLLM(structured_responses=_extraction([]))
    await memory_service.extract_and_save("u1", "哈哈哈哈", "是呀", llm=llm)
    assert repo.list_by_user("u1") == []


async def test_ai_inferred_never_saved(db_session_factory):
    llm = FakeLLM(
        structured_responses=_extraction(
            [_save_candidate("用户很开心", source="ai_inferred", importance=0.9)]
        )
    )
    await memory_service.extract_and_save("u1", "哈哈哈今天真开心", "是呀", llm=llm)
    assert repo.list_by_user("u1") == []


async def test_exact_duplicate_not_saved_twice(db_session_factory):
    llm = FakeLLM(structured_responses=_extraction([_save_candidate("用户喜欢寿司")]))
    await memory_service.extract_and_save("u1", "a", "b", llm=llm)
    llm2 = FakeLLM(structured_responses=_extraction([_save_candidate("用户喜欢寿司")]))
    await memory_service.extract_and_save("u1", "a", "b", llm=llm2)
    memories = [m for m in repo.list_by_user("u1") if m.memory == "用户喜欢寿司"]
    assert len(memories) == 1


async def test_dedup_scoped_per_user(db_session_factory):
    llm = FakeLLM(structured_responses=_extraction([_save_candidate("用户喜欢寿司")]))
    await memory_service.extract_and_save("u1", "a", "b", llm=llm)
    await memory_service.extract_and_save("u2", "a", "b", llm=llm)
    assert len(repo.list_by_user("u1")) == 1
    assert len(repo.list_by_user("u2")) == 1

