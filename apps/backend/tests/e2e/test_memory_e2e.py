import json

from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from app.repositories import memory_repository as repo
from tests.conftest import FakeLLM, wait_until


def _client():
    return TestClient(app)


def _parse_stream(text):
    return [json.loads(line) for line in text.strip().splitlines() if line.strip()]


_ROLE_MODE = {
    "mode": "default",
    "intent": "casual",
    "confidence": 0.9,
    "reason": "hi",
}


def _extraction(candidates):
    return {"RoleMode": _ROLE_MODE, "MemoryExtraction": {"candidates": candidates}}


def _save_candidate(content, **overrides):
    payload = {
        "action": "save",
        "type": "user_preference",
        "content": content,
        "importance": 0.8,
        "confidence": 0.95,
        "source": "user_stated",
    }
    payload.update(overrides)
    return payload


def test_extractor_failure_does_not_break_sse(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["记得", "呀"],
        structured_errors={"MemoryExtraction": RuntimeError("extractor down")},
    )
    llm_factory.set_llm(llm)
    try:
        with _client() as client:
            resp = client.post("/api/v1/chat/message", json={"content": "我喜欢寿司"})
            assert resp.status_code == 200
            events = _parse_stream(resp.text)
            deltas = [e for e in events if "delta" in e]
            assert [d["delta"] for d in deltas] == ["记得", "呀"]
            assert events[-1].get("done") is True
            assert not any(
                m.content == "用户喜欢寿司"
                for m in repo.list_by_user("default-user")
            )
    finally:
        llm_factory.reset_llm()


def test_memory_roundtrip_across_turns(db_session_factory, fake_llm):
    llm = fake_llm(
        response=["好的"],
        structured_responses=_extraction([_save_candidate("用户喜欢西瓜")]),
    )
    llm_factory.set_llm(llm)
    try:
        with _client() as client:
            resp = client.post("/api/v1/chat/message", json={"content": "我喜欢西瓜"})
            session_id = resp.headers["x-session-id"]
            assert resp.status_code == 200
            assert wait_until(
                lambda: any(
                    m.content == "用户喜欢西瓜"
                    for m in repo.list_by_user("default-user")
                )
            )

            recall_llm = fake_llm(
                response=["记得", "呀"],
                structured_responses=_extraction([]),
            )
            llm_factory.set_llm(recall_llm)
            resp2 = client.post(
                "/api/v1/chat/message",
                json={"session_id": session_id, "content": "你还记得我喜欢吃什么吗"},
            )
            assert resp2.status_code == 200
            prompt_texts = [str(m) for m in recall_llm.seen_messages]
            assert any("用户喜欢西瓜" in t for t in prompt_texts)
    finally:
        llm_factory.reset_llm()
