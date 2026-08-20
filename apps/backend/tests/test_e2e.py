import json

import pytest
from fastapi.testclient import TestClient

from app.core import llm_factory
from app.main import app
from app.repositories import memory_repository, summary_repository

from tests.conftest import wait_until


@pytest.fixture
def client_fixture():
    with TestClient(app) as test_client:
        yield test_client


def _parse_stream(text):
    return [json.loads(line) for line in text.strip().splitlines()]


def _structured_responses(**memory):
    base = {
        "RoleMode": {
            "mode": "default",
            "intent": "casual",
            "confidence": 0.9,
            "reason": "hi",
        },
    }
    base["MemoryDecision"] = {
        "should_save": memory.get("should_save", False),
        "memory": memory.get("memory"),
        "memory_type": memory.get("memory_type", "preference"),
        "importance": memory.get("importance", 0.0),
    }
    return base


def test_health(client_fixture):
    assert client_fixture.get("/health").json() == {"status": "ok"}


def test_empty_content_422(client_fixture):
    resp = client_fixture.post("/api/v1/chat/message", json={"content": ""})
    assert resp.status_code == 422


def test_stream_contract_and_session_create(
    client_fixture, db_session_factory, fake_llm
):
    llm_factory.set_llm(
        fake_llm(
            response=["你好", "呀"],
            structured_responses=_structured_responses(),
        )
    )
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "在吗"})
    assert resp.status_code == 200
    assert resp.headers.get("x-session-new") == "true"
    session_id = resp.headers.get("x-session-id")
    lines = _parse_stream(resp.text)
    deltas = "".join(line.get("delta", "") for line in lines if "delta" in line)
    assert deltas == "你好呀"
    assert lines[-1]["done"] is True
    assert lines[-1]["session_id"] == session_id


def test_existing_session_no_new_header(client_fixture, db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["ok"],
            structured_responses=_structured_responses(),
        )
    )
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "先来一轮"})
    session_id = resp.headers.get("x-session-id")
    resp2 = client_fixture.post(
        "/api/v1/chat/message",
        json={"session_id": session_id, "content": "再一轮"},
    )
    assert resp2.headers.get("x-session-new") is None


def test_second_turn_knows_first(client_fixture, db_session_factory, fake_llm):
    llm = fake_llm(
        response=["收到"],
        structured_responses=_structured_responses(),
    )
    llm_factory.set_llm(llm)
    resp = client_fixture.post(
        "/api/v1/chat/message", json={"content": "我在学 LangGraph"}
    )
    session_id = resp.headers.get("x-session-id")
    resp2 = client_fixture.post(
        "/api/v1/chat/message",
        json={"session_id": session_id, "content": "Runnable 是什么"},
    )
    assert resp2.status_code == 200
    prompt_text = str(llm.seen_messages[-1])
    assert "我在学 LangGraph" in prompt_text


def test_memory_roundtrip(client_fixture, db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=["好的"],
            structured_responses=_structured_responses(
                should_save=True,
                memory="用户喜欢寿司",
                memory_type="preference",
                importance=0.8,
            ),
        )
    )
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "我喜欢寿司"})
    session_id = resp.headers.get("x-session-id")
    assert resp.status_code == 200
    assert wait_until(
        lambda: any(
            m.memory == "用户喜欢寿司"
            for m in memory_repository.list_by_user("default-user")
        )
    )

    llm = fake_llm(
        response=["嗯"],
        structured_responses=_structured_responses(),
    )
    llm_factory.set_llm(llm)
    client_fixture.post(
        "/api/v1/chat/message",
        json={"session_id": session_id, "content": "晚上想吃寿司"},
    )
    assert wait_until(lambda: any("用户喜欢寿司" in str(m) for m in llm.seen_messages))


def test_summary_trigger_after_threshold(
    client_fixture, db_session_factory, fake_llm, override_settings
):
    override_settings(summary_threshold=4)
    llm_factory.set_llm(
        fake_llm(
            response=["嗯嗯"],
            structured_responses=_structured_responses(),
        )
    )
    session_id = None
    for i in range(2):
        body = {"content": f"第{i}轮"}
        if session_id:
            body["session_id"] = session_id
        resp = client_fixture.post("/api/v1/chat/message", json=body)
        session_id = resp.headers.get("x-session-id")
    assert wait_until(lambda: summary_repository.get_summary(session_id) is not None)


def test_llm_failure_streams_detail(client_fixture, db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(
            response=[],
            structured_responses=_structured_responses(),
        )
    )
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "会不会崩"})
    lines = _parse_stream(resp.text)
    assert any(line.get("detail") == "LLM 调用失败" for line in lines)


def test_router_low_confidence_degrades_to_default(
    client_fixture, db_session_factory, fake_llm
):
    llm = fake_llm(
        response=["嗯嗯"],
        structured_responses={
            "RoleMode": {
                "mode": "professional",
                "intent": "technical",
                "confidence": 0.3,
                "reason": "不确定用户意图",
            },
            "MemoryDecision": {
                "should_save": False,
                "memory": None,
                "memory_type": "preference",
                "importance": 0.0,
            },
        },
    )
    llm_factory.set_llm(llm)
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "随便聊聊"})
    assert resp.status_code == 200
    assert any("日常模式" in str(m) for m in llm.seen_messages)
    assert not any("专业模式" in str(m) for m in llm.seen_messages)


def test_router_high_confidence_keeps_mode(
    client_fixture, db_session_factory, fake_llm
):
    llm = fake_llm(
        response=["嗯嗯"],
        structured_responses={
            "RoleMode": {
                "mode": "professional",
                "intent": "technical",
                "confidence": 0.9,
                "reason": "明确的编程问题",
            },
            "MemoryDecision": {
                "should_save": False,
                "memory": None,
                "memory_type": "preference",
                "importance": 0.0,
            },
        },
    )
    llm_factory.set_llm(llm)
    resp = client_fixture.post("/api/v1/chat/message", json={"content": "Python 报错"})
    assert resp.status_code == 200
    assert any("专业模式" in str(m) for m in llm.seen_messages)
