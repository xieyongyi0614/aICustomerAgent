"""V6.5-006 Case 11/12：mode 会话序列 + 持久化。"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import llm_factory
from app.main import app
from app.repositories import conversation_repository as repo
from tests.conftest import wait_until


@pytest.fixture
def client(db_session_factory):
    with TestClient(app) as test_client:
        yield test_client


IMMERSIVE = {
    "mode": "immersive",
    "intent": "emotional",
    "confidence": 0.9,
    "reason": "情绪倾诉",
}


def _post(client, content, session_id=None):
    body = {"content": content}
    if session_id:
        body["session_id"] = session_id
    resp = client.post("/api/v1/chat/message", json=body)
    assert resp.status_code == 200
    return json.loads(resp.text.splitlines()[0])


def _new_session(client, content):
    resp = client.post("/api/v1/chat/message", json={"content": content})
    assert resp.status_code == 200
    meta = json.loads(resp.text.splitlines()[0])
    return meta, resp.headers.get("x-session-id")


def test_mode_hysteresis_switch_after_two_turns(client, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["嗯"],
            structured_responses={
                "RoleMode": IMMERSIVE,
                "TurnAnalysis": {
                    "user_emotion": {"emotion": "neutral", "event": "daily"},
                    "behavior": {"behavior": "normal_reply", "reason": ""},
                },
            },
        )
    )
    meta1, session_id = _new_session(client, "在吗")
    assert meta1["mode"]["effective"] == "default"
    assert meta1["mode"]["switched"] is False

    meta2 = _post(client, "陪陪我", session_id)
    assert meta2["mode"]["effective"] == "immersive"
    assert meta2["mode"]["switched"] is True

    def _check():
        row = repo.find_conversation(session_id)
        return row is not None and row.mode == "immersive"

    assert wait_until(_check)


def test_router_failure_keeps_confirmed_mode(client, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["嗯"],
            structured_responses={
                "RoleMode": IMMERSIVE,
                "TurnAnalysis": {
                    "user_emotion": {"emotion": "neutral", "event": "daily"},
                    "behavior": {"behavior": "normal_reply", "reason": ""},
                },
            },
        )
    )
    meta1, session_id = _new_session(client, "在吗")
    _post(client, "陪陪我", session_id)

    llm_factory.set_llm(
        fake_llm(
            response=["嗯"],
            structured_responses={
                "TurnAnalysis": {
                    "user_emotion": {"emotion": "neutral", "event": "daily"},
                    "behavior": {"behavior": "normal_reply", "reason": ""},
                },
            },
            structured_errors={"RoleMode": RuntimeError("router boom")},
        )
    )
    meta3 = _post(client, "还在吗", session_id)
    assert meta3["mode"]["confirmed"] == "immersive"
    assert meta3["mode"]["effective"] == "immersive"
    assert meta3["mode"]["switched"] is False


def test_existing_conversation_row_has_default_mode(client, fake_llm):
    llm_factory.set_llm(fake_llm(response=["嗯"]))
    resp = client.post("/api/v1/chat/message", json={"content": "在吗"})
    session_id = resp.headers.get("x-session-id")
    row = repo.find_conversation(session_id)
    assert row is not None
    assert row.mode == "default"
    assert row.mode_entered_at is None
