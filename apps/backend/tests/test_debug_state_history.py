import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories import (
    conversation_repository,
    emotion_history_repository,
    memory_repository,
)
from tests.conftest import wait_until


@pytest.fixture()
def client(db_session_factory, llm_override, fake_llm):
    llm_override(
        fake_llm(
            response=["好耶"],
            structured_responses={
                "RoleMode": {
                    "mode": "default",
                    "intent": "casual",
                    "confidence": 0.9,
                    "reason": "hi",
                },
                "TurnAnalysis": {
                    "user_emotion": {"emotion": "happy", "event": "achievement"},
                    "behavior": {"behavior": "celebrate", "reason": "用户达成成就"},
                },
                "StateUpdateDecision": {
                    "mood": "happy",
                    "mood_reason": "好消息",
                    "inner_state": "开心",
                    "current_topic": "项目上线",
                },
                "MemoryDecision": {
                    "should_save": True,
                    "memory": "用户喜欢寿司",
                    "memory_type": "preference",
                    "importance": 0.8,
                },
            },
        )
    )
    with TestClient(app) as test_client:
        yield test_client


def _post_message(client, content, session_id=None):
    body = {"content": content}
    if session_id:
        body["session_id"] = session_id
    return client.post("/api/v1/chat/message", json=body)


def test_state_returns_defaults_for_fresh_user(client):
    resp = client.get("/api/v1/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["character_state"]["mood"] == "calm"
    assert data["relationship_state"]["stage"] == "friend"
    assert data["character_state"]["updated_at"] is None
    assert data["emotion_history"] == []


def test_state_reflects_turn_and_respects_limit(client):
    resp = _post_message(client, "我今天终于把项目上线了")
    session_id = resp.headers["x-session-id"]
    assert wait_until(
        lambda: len(emotion_history_repository.list_recent("default-user", 5)) >= 1
    )

    for i in range(3):
        emotion_history_repository.append(
            user_id="default-user",
            session_id=session_id,
            user_emotion="neutral",
            event="daily",
            behavior="normal_reply",
            mood_before="calm",
            mood_after="calm",
            energy_after=0.8,
            stage_after="friend",
        )

    full = client.get("/api/v1/state").json()
    assert full["character_state"]["mood"] == "happy"
    assert full["character_state"]["current_topic"] == "项目上线"
    assert full["relationship_state"]["updated_at"] is not None
    assert len(full["emotion_history"]) >= 4

    limited = client.get("/api/v1/state?limit=2").json()
    assert len(limited["emotion_history"]) == 2


def test_messages_404_for_unknown_conversation(client):
    resp = client.get("/api/v1/conversations/nope/messages")
    assert resp.status_code == 404


def test_messages_returned_in_ascending_order_with_limit(client):
    session_id = None
    for i in range(3):
        resp = _post_message(client, f"第{i}句", session_id)
        session_id = resp.headers["x-session-id"]

    data = client.get(f"/api/v1/conversations/{session_id}/messages").json()
    ids = [m["id"] for m in data["messages"]]
    assert ids == sorted(ids)
    assert [m["content"] for m in data["messages"]][:3] == ["第0句", "好耶", "第1句"]

    paged = client.get(
        f"/api/v1/conversations/{session_id}/messages?limit=2&before_id={ids[-2]}"
    ).json()
    paged_ids = [m["id"] for m in paged["messages"]]
    assert paged_ids == sorted(paged_ids)
    assert all(m["id"] < ids[-2] for m in paged["messages"])
    assert len(paged["messages"]) == 2


def test_memories_isolated_by_user_after_roundtrip(client):
    assert client.get("/api/v1/memories").json()["memories"] == []

    resp = _post_message(client, "我喜欢寿司")
    assert resp.status_code == 200
    assert wait_until(
        lambda: any(
            m.memory == "用户喜欢寿司"
            for m in memory_repository.list_by_user("default-user")
        )
    )

    mine = client.get("/api/v1/memories").json()
    assert any(m["memory"] == "用户喜欢寿司" for m in mine["memories"])
    assert mine["user_id"] == "default-user"

    other = client.get("/api/v1/memories?user_id=someone-else").json()
    assert other["memories"] == []


def test_messages_endpoint_does_not_create_conversation(client):
    before = conversation_repository.find_conversation("ghost-session")
    assert before is None
    assert client.get("/api/v1/conversations/ghost-session/messages").status_code == 404
    assert conversation_repository.find_conversation("ghost-session") is None
