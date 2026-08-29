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


async def test_retrieve_hits_matching_memory(db_session_factory):
    repo.create_memory("u1", "用户喜欢寿司", "preference", 0.8)
    repo.create_memory("u1", "用户在学 Python", "goal", 0.7)
    hits = memory_service.retrieve("u1", "我想吃寿司", top_k=5)
    assert any(m.memory == "用户喜欢寿司" for m in hits)


async def test_retrieve_empty_result(db_session_factory):
    repo.create_memory("u1", "用户喜欢寿司", "preference", 0.8)
    assert memory_service.retrieve("u1", "完全不相关的 zzz", top_k=5) == []


async def test_extract_failure_skipped(db_session_factory):
    llm = FakeLLM(raise_exc=RuntimeError("boom"))
    await memory_service.extract_and_save("u1", "x", "y", llm=llm)
    assert repo.list_by_user("u1") == []


async def test_suppress_blocks_whole_round(db_session_factory):
    llm = FakeLLM(
        structured_responses=_extraction(
            [
                _save_candidate("用户在深圳工作", memory_type="user_fact"),
                {
                    "action": "suppress",
                    "type": "user_fact",
                    "content": "用户的收入信息",
                    "importance": 0.9,
                    "confidence": 0.95,
                    "source": "user_stated",
                },
            ]
        )
    )
    await memory_service.extract_and_save("u1", "别记住这件事，对了我在深圳工作", "明白", llm=llm)
    assert repo.list_by_user("u1") == []


async def test_forget_hard_deletes_matching_memory(db_session_factory):
    existing = repo.create_memory_v4(
        "u1", "asuna", "用户喜欢咖啡", "user_preference", 0.8, 0.9
    )
    llm = FakeLLM(
        structured_responses=_extraction(
            [
                {
                    "action": "forget",
                    "type": "user_preference",
                    "content": "用户喜欢咖啡",
                    "importance": 0.5,
                    "confidence": 0.95,
                    "source": "user_stated",
                }
            ]
        )
    )
    await memory_service.extract_and_save("u1", "把喜欢咖啡的事忘了吧", "好的", llm=llm)
    assert repo.get_memory_v4(existing.id) is None


async def test_forget_without_match_deletes_nothing(db_session_factory):
    existing = repo.create_memory_v4(
        "u1", "asuna", "用户喜欢咖啡", "user_preference", 0.8, 0.9
    )
    llm = FakeLLM(
        structured_responses=_extraction(
            [
                {
                    "action": "forget",
                    "type": "user_preference",
                    "content": "用户喜欢奶茶",
                    "importance": 0.5,
                    "confidence": 0.95,
                    "source": "user_stated",
                }
            ]
        )
    )
    await memory_service.extract_and_save("u1", "把喜欢奶茶的事忘了吧", "好的", llm=llm)
    assert repo.get_memory_v4(existing.id) is not None


async def test_invalidate_marks_old_row_only(db_session_factory):
    existing = repo.create_memory_v4(
        "u1", "asuna", "用户喜欢咖啡", "user_preference", 0.8, 0.9
    )
    llm = FakeLLM(
        structured_responses=_extraction(
            [
                {
                    "action": "invalidate",
                    "type": "user_preference",
                    "content": "用户喜欢咖啡",
                    "importance": 0.5,
                    "confidence": 0.95,
                    "source": "user_stated",
                }
            ]
        )
    )
    await memory_service.extract_and_save("u1", "我现在已经不喝咖啡了", "了解", llm=llm)
    row = repo.get_memory_v4(existing.id)
    assert row.status == "invalidated"
    assert repo.list_active_v4("u1", "asuna") == []


async def test_conflicting_update_supersedes_old(db_session_factory):
    existing = repo.create_memory_v4(
        "u1", "asuna", "用户喜欢咖啡", "user_preference", 0.8, 0.9
    )
    llm = FakeLLM(
        structured_responses=_extraction([_save_candidate("用户喜欢喝茶", relation="replace")])
    )
    await memory_service.extract_and_save("u1", "我现在喜欢喝茶了", "好呀", llm=llm)
    active = repo.list_active_v4("u1", "asuna")
    assert [m.content for m in active] == ["用户喜欢喝茶"]
    old = repo.get_memory_v4(existing.id)
    assert old.status == "superseded"
    assert old.superseded_by == active[0].id


async def test_refine_updates_existing_row(db_session_factory):
    existing = repo.create_memory_v4(
        "u1", "asuna", "用户喜欢咖啡", "user_preference", 0.8, 0.9
    )
    llm = FakeLLM(
        structured_responses=_extraction(
            [_save_candidate("用户喜欢冰美式咖啡", relation="refine")]
        )
    )
    await memory_service.extract_and_save("u1", "我只喝冰美式", "好呀", llm=llm)
    assert len(repo.list_active_v4("u1", "asuna")) == 1
    updated = repo.get_memory_v4(existing.id)
    assert updated.content == "用户喜欢冰美式咖啡"
    assert updated.status == "active"
