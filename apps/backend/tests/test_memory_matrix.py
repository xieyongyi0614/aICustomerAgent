"""V4 测试矩阵聚合用例：testing.md 十项必测中 Case 1~9 的管线级断言。

Case 10（V2/V3 全量回归零破坏）由全量 pytest 运行本身覆盖。
"""

from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from app.repositories import memory_repository as repo
from app.services import memory_service
from tests.conftest import FakeLLM


def _extraction(candidates):
    return {"MemoryExtraction": {"candidates": candidates}}


def _candidate(content, memory_type, **overrides):
    payload = {
        "action": "save",
        "type": memory_type,
        "content": content,
        "importance": 0.8,
        "confidence": 0.95,
        "source": "user_stated",
    }
    payload.update(overrides)
    return payload


async def _run(db_session_factory, candidates, user_input="x", ai_reply="y"):
    llm = FakeLLM(structured_responses=_extraction(candidates))
    await memory_service.extract_and_save("u1", user_input, ai_reply, llm=llm)


async def test_case_1_user_preference_extracted_and_saved(db_session_factory):
    await _run(
        db_session_factory,
        [_candidate("用户不喝咖啡", "user_preference")],
        "我从来不喝咖啡",
    )
    active = repo.list_active_v4("u1", "asuna")
    assert len(active) == 1
    assert active[0].type == "user_preference"
    assert active[0].source == "user_stated"


async def test_case_2_user_fact_extracted_and_saved(db_session_factory):
    await _run(
        db_session_factory,
        [_candidate("用户养了一只猫，猫三岁", "user_fact")],
        "我家猫三岁了",
    )
    active = repo.list_active_v4("u1", "asuna")
    assert active[0].type == "user_fact"


async def test_case_3_chitchat_saves_nothing(db_session_factory):
    await _run(db_session_factory, [], "今天天气不错")
    assert repo.list_by_user("u1") == []


async def test_case_4_ai_inferred_discarded(db_session_factory):
    await _run(
        db_session_factory,
        [_candidate("用户很开心", "user_preference", source="ai_inferred")],
        "哈哈",
        "你一定很开心",
    )
    assert repo.list_by_user("u1") == []


async def test_case_5_retrieval_filters_and_orders(db_session_factory):
    repo.create_memory_v4("u1", "asuna", "用户喜欢西瓜", "user_preference", 0.9, 0.95)
    repo.create_memory_v4("u1", "asuna", "用户喜欢草莓", "user_preference", 0.9, 0.9)
    invalidated = repo.create_memory_v4(
        "u1", "asuna", "用户喜欢榴莲", "user_preference", 0.9, 0.95
    )
    repo.invalidate_memory(invalidated.id)
    results = memory_service.retrieve_v4("u1", "我喜欢什么水果", character_id="asuna")
    contents = [m.content for m in results]
    assert "用户喜欢榴莲" not in contents
    assert "用户喜欢西瓜" in contents
    assert memory_service.retrieve_v4(
        "u1", "随便聊聊别的", character_id="asuna", top_k=5
    )


async def test_case_6_conflict_leaves_single_active_memory(db_session_factory):
    repo.create_memory_v4("u1", "asuna", "用户喜欢咖啡", "user_preference", 0.8, 0.9)
    await _run(
        db_session_factory,
        [_candidate("用户喜欢喝茶", "user_preference", relation="replace")],
        "我现在改成喜欢喝茶了",
    )
    active = repo.list_active_v4("u1", "asuna")
    assert [m.content for m in active] == ["用户喜欢喝茶"]


async def test_case_7_privacy_suppress_zero_write_and_forget_hard_delete(
    db_session_factory,
):
    await _run(
        db_session_factory,
        [
            _candidate("用户在深圳工作", "user_fact"),
            {
                "action": "suppress",
                "type": "user_fact",
                "content": "用户的收入信息",
                "importance": 0.9,
                "confidence": 0.95,
                "source": "user_stated",
            },
        ],
        "别记住这件事",
    )
    assert repo.list_by_user("u1") == []

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
    await memory_service.extract_and_save("u1", "咖啡的事忘了吧", "好的", llm=llm)
    assert repo.get_memory_v4(existing.id) is None


async def test_case_8_modify_old_memory_supersedes(db_session_factory):
    old = repo.create_memory_v4(
        "u1", "asuna", "用户喜欢咖啡", "user_preference", 0.8, 0.9
    )
    await _run(
        db_session_factory,
        [_candidate("用户喜欢喝茶", "user_preference", relation="replace")],
        "我现在改成喜欢喝茶了",
    )
    old_row = repo.get_memory_v4(old.id)
    assert old_row.status == "superseded"
    active = repo.list_active_v4("u1", "asuna")
    assert [m.content for m in active] == ["用户喜欢喝茶"]
    assert old_row.superseded_by == active[0].id


def test_case_9_memory_failure_does_not_break_sse(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["你好", "呀"],
        structured_errors={"MemoryExtraction": RuntimeError("extractor down")},
    )
    llm_factory.set_llm(llm)
    try:
        with TestClient(app) as client:
            resp = client.post("/api/v1/chat/message", json={"content": "在吗"})
            assert resp.status_code == 200
            import json

            events = [
                json.loads(line)
                for line in resp.text.strip().splitlines()
                if line.strip()
            ]
            assert [e["delta"] for e in events if "delta" in e] == ["你好", "呀"]
            assert events[-1].get("done") is True
    finally:
        llm_factory.reset_llm()
